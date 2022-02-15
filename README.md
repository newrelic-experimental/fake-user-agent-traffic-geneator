# Fake traffic generator for Gartner Demo

Generate fake traffic to URLs with custom user-agents

## Usage

![Running](./screenshot-running.png)
![Complete](./screenshot-complete.png)

**Tested with Python 3.9.5 and pip 22.0.3 on MacOS 10.15.7**

I highly recommend you always run each Python project within its own virtualenv. The commands below assume you have already created and activated a virtualenv for this project.

```
git clone git@github.com:newrelic-experimental/fake-user-agent-traffic-geneator.git
cd fake-user-agent-traffic-geneator
pip install -r requirements.txt
python generate.py
```

## Config

Configuration is done via the `config.toml` file.

### Global settings

| Name        | Type      | Description            |
| ----------- | --------- | ---------------------- |
| concurrency | int       | max asyncio primitives |
| urls        | list[str] | List of URLs to target |

### Target settings

The target of each request is grouped together into Targets

| Name                  | Type                                | Description                                        |
| --------------------- | ----------------------------------- | -------------------------------------------------- |
| allowed_request_types | list[str]                           | Allowed request types                              |
| url                   | str                                 | The URL to request                                 |
| form                  | Optional[Dict[str, Dict[str, str]]] | Form submission details for request (browser only) |
| form.button_selector  | str                                 | CSS selector of the form submit button             |
| form.inputs.selector  | str                                 | CSS selector for form input field                  |
| form.inputs.value     | str                                 | Value to enter into form input field               |

### Request settings

Request specific settings are grouped together into Personas, you can create as many personas as you would like for each run.

| Name           | Type                           | Description                                                                  |
| -------------- | ------------------------------ | ---------------------------------------------------------------------------- |
| request_type   | "browser" or "api"             | How the request should be executed ("browser" is required for RUM)           |
| min_requests   | int                            | Minimum number of requests to make per URL                                   |
| max_requests   | int                            | Maximum number of requests to make per URL                                   |
| timeout        | Optional[int]                  | Request timeout in seconds                                                   |
| cache_enabled  | Optional[bool]                 | Enable browser cache (only used when browser=true)                           |
| user_agents    | list[str]                      | User-Agent strings to use. A random ua will be choosen per request           |
| custom_headers | Optional[list[list[str, str]]] | Any other headers to send with the request. See the example below for syntax |
| color          | str                            | Persona text color in progress bar                                           |

Each custom header must be a list where index 0 is the header key and index 1 is the header value. For example:

`custom_headers = [["X-Script-Version", "v0.0.1"], ["X-Something-else", "abc"]]`
