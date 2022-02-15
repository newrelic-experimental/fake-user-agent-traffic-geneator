import asyncio
import httpx
from pyppeteer import launch
import toml
import time
import random
from datetime import timedelta
from typing import NewType
from attrs import define
from rich import print
from rich.console import Console
from rich.markdown import Markdown
from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn
from rich.live import Live
from rich.panel import Panel
from rich.table import Table

from textual import events
from textual.app import App
from textual.widgets import Footer, ScrollView

TaskID = NewType("TaskID", int)

response_status_by_persona = {}
exceptions_by_persona = {}


def add_response_status(request, status_code):
    name = f"{request.persona} {'(browser)' if request.browser else '(API)'}"

    if name not in response_status_by_persona:
        response_status_by_persona[name] = {}

    response_status_by_persona[name][status_code] = (
        response_status_by_persona[name].get(status_code, 0) + 1
    )


def add_exception(request, e):
    name = f"{request.persona} {'(browser)' if request.browser else '(API)'}"

    if name not in exceptions_by_persona:
        exceptions_by_persona[name] = {}

    exceptions_by_persona[name][type(e).__name__] = (
        exceptions_by_persona[name].get(type(e).__name__, 0) + 1
    )


class TextualExtended(App):
    def __init__(self, stats, response_log, *args, **kwargs):
        self.stats = stats
        self.response_log = response_log

        super().__init__(*args, **kwargs)

    @classmethod
    def run(
        cls,
        console=None,
        screen=True,
        driver=None,
        loop=None,
        **kwargs,
    ):
        async def run_app() -> None:
            app = cls(screen=screen, driver_class=driver, **kwargs)
            await app.process_messages()

        loop.create_task(run_app())


class FakeTraffic(TextualExtended):
    async def on_load(self, event: events.Load) -> None:
        """Bind keys with the app loads (but before entering application mode)"""
        await self.bind("q", "quit", "Quit")

    async def on_mount(self, event: events.Mount) -> None:
        response_log_view = ScrollView(gutter=1)
        stats_view = ScrollView(gutter=1)

        # footer / sidebar / body
        await self.view.dock(Footer(), edge="bottom")
        await self.view.dock(stats_view, edge="left", size=30, name="stats_view")
        await self.view.dock(response_log_view, edge="right", name="response_log_view")

        async def render_response_log(response_log: str) -> None:
            await response_log_view.update(Markdown(response_log, hyperlinks=True))

        async def render_stats_view(stats: str) -> None:
            await stats_view.update(Markdown(stats, hyperlinks=True))

        await self.call_later(render_response_log, self.response_log)
        await self.call_later(render_stats_view, self.stats)


@define
class RequestByPersona:
    persona: str
    url: str
    ua: str
    browser: bool
    timeout: int
    cache_enabled: bool
    custom_headers: list[str]
    task: TaskID


def update_all_progress(job_progress, overall_progress, task_id):
    job_progress.advance(task_id)


class ProgressManager:
    def __init__(self, overall_progress, job_progress):
        self.overall_progress = overall_progress
        self.job_progress = job_progress
        self.overall_task = self.overall_progress.add_task("All Jobs")
        self.tasks_by_persona = {}

    def add_task(self, name):
        if name in self.tasks_by_persona:
            self.job_progress.update(
                self.tasks_by_persona[name],
                total=self.job_progress._tasks[self.tasks_by_persona[name]].total + 1,
            )
        else:
            self.tasks_by_persona[name] = self.job_progress.add_task(name, total=1)

        total = sum(task.total for task in self.job_progress.tasks)
        self.overall_progress.update(self.overall_task, total=total)

        return self.tasks_by_persona[name]

    def advance(self, task_id):
        self.job_progress.advance(task_id)
        completed = sum(task.completed for task in self.job_progress.tasks)
        self.overall_progress.update(self.overall_task, completed=completed)


async def make_request(request, browser, progress):
    if request.browser:
        try:
            page = await browser.newPage()
            await page.setUserAgent(request.ua)
            await page.setExtraHTTPHeaders(request.custom_headers)
            await page.setCacheEnabled(request.cache_enabled)
            browser_response = await page.goto(
                request.url, timeout=request.timeout * 1000
            )

            api_request = httpx.Request(
                method="GET",
                url=request.url,
                headers=browser_response.headers,
            )
            api_response = httpx.Response(
                status_code=browser_response.status, request=api_request
            )
            metrics = await page.metrics()
            await page.close()

            api_response._elapsed = timedelta(milliseconds=metrics["TaskDuration"])
            api_response.close()

            add_response_status(request, browser_response.status)

            progress.advance(request.task)
            return api_response
        except Exception as e:
            add_exception(request, e)
            progress.advance(request.task)
    else:
        try:
            async with httpx.AsyncClient(
                headers={**request.custom_headers, **{"User-Agent": request.ua}}
            ) as client:
                response = await client.get(request.url, timeout=request.timeout)

                add_response_status(request, response.status_code)
                progress.advance(request.task)
                return response
        except Exception as e:
            add_exception(request, e)
            progress.advance(request.task)


async def gather_tasks(concurrency, requests, browser, progress):
    semaphore = asyncio.Semaphore(concurrency)

    tasks = []
    for request in requests:
        task = asyncio.create_task(make_request(request, browser, progress))
        tasks.append(task)

    async def sem_task(task):
        async with semaphore:
            return await task

    return await asyncio.gather(*(sem_task(task) for task in tasks))


async def prepare_requests(config, browser, progress):
    requests = []

    for url in config["urls"]:
        for key, persona in config["personas"].items():
            for _ in range(
                random.randint(persona["min_requests"], persona["max_requests"])
            ):
                requests.append(
                    RequestByPersona(
                        persona=key,
                        url=url,
                        ua=random.choice(persona["user_agents"]),
                        timeout=persona["timeout"],
                        cache_enabled=persona["cache_enabled"],
                        browser=persona["browser"],
                        custom_headers={h[0]: h[1] for h in persona["custom_headers"]},
                        task=progress.add_task(f"[{persona['color']}]{key}"),
                    )
                )

    return await gather_tasks(config["concurrency"], requests, browser, progress)


async def main():
    import warnings

    warnings.filterwarnings("ignore")

    console = Console()
    console.clear()

    config = toml.load("./config.toml")
    browser = await launch()

    job_progress = Progress(
        "{task.description}",
        SpinnerColumn(),
        BarColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
    )

    overall_progress = Progress()

    progress = ProgressManager(overall_progress, job_progress)

    progress_table = Table.grid()
    progress_table.add_row(
        Panel.fit(
            overall_progress,
            title="Overall Progress",
            border_style="yellow",
            padding=(2, 2),
        ),
        Panel.fit(job_progress, title="[b]Jobs", border_style="yellow", padding=(1, 2)),
    )

    with Live(progress_table, refresh_per_second=10):
        requests_results = await prepare_requests(config, browser, progress)

    stats_md = ["# Requests\n"]

    for persona_name, statuses in response_status_by_persona.items():
        stats_md.append(f"- {persona_name}")

        for code, count in statuses.items():
            stats_md.append(f"- **{code}:** {count}")

        stats_md.append(f"\n")
        stats_md.append(f"---")
        stats_md.append(f"\n")

    if len(exceptions_by_persona) > 0:
        stats_md.append("# Exceptions\n")

        for persona_name, exceptions in exceptions_by_persona.items():
            stats_md.append(f"- {persona_name}")

            for exception_name, count in exceptions.items():
                stats_md.append(f"- **{exception_name}:** {count}")

            stats_md.append(f"\n")
            stats_md.append(f"---")
            stats_md.append(f"\n")

    response_log_md = ["# Response Log"]
    response_log_md.append(
        f"{len(requests_results)} requests made across {len(config['personas'])} personas\n"
    )

    for response in requests_results:
        if response:
            elapsed = (
                f"{response.elapsed.total_seconds()}s"
                if response.status_code != 417
                else "--"
            )

            response_log_md.append(
                f"- **{response.status_code}** ◦ [{response.url.path}]({response.url}) ◦ {elapsed}"
            )

    terminal_app = FakeTraffic(
        stats="\n".join(stats_md),
        response_log="\n".join(response_log_md),
        title="Fake Traffic App",
        log="textual.log",
    )

    await terminal_app.process_messages()


if __name__ == "__main__":
    asyncio.run(main())
