import json
import os
import time

import litellm
from beartype import beartype
from beartype.typing import Any, Dict, List, Optional
from litellm.types.utils import Message

from marble.llms.error_handler import api_calling_error_exponential_backoff
from marble.utils.trace import record_call

# Local vLLM routing: model name -> (url, api_key), loaded from the shared model_config.json.
# Defaults to workflow-experiment/serving/model_config.json; set MARBLE_MODEL_CONFIG to use another file.
_ROUTES: Dict[str, Any] = {}
_ROUTE_FILE = os.environ.get(
    "MARBLE_MODEL_CONFIG",
    os.path.join(os.path.dirname(__file__), "../../../serving/model_config.json"),
)
if os.path.isfile(_ROUTE_FILE):
    with open(_ROUTE_FILE) as f:
        for name, v in json.load(f)["model_dict"].items():
            m = v["model_list"][0]
            _ROUTES[name] = (m["model_url"], m.get("api_key", "EMPTY"))


@beartype
@api_calling_error_exponential_backoff(retries=5, base_wait_time=1)
def model_prompting(
    llm_model: str,
    messages: List[Dict[str, str]],
    return_num: Optional[int] = 1,
    max_token_num: Optional[int] = 512,
    temperature: Optional[float] = 0.0,
    top_p: Optional[float] = None,
    stream: Optional[bool] = None,
    mode: Optional[str] = None,
    tools: Optional[List[Dict[str, Any]]] = None,
    tool_choice: Optional[str] = None,
) -> List[Message]:
    """
    Select model via router in LiteLLM with support for function calling.
    """
    # litellm.set_verbose=True
    model_name = llm_model
    api_key = None
    if llm_model in _ROUTES:
        base_url, api_key = _ROUTES[llm_model]
        llm_model = "openai/" + llm_model  # use the OpenAI-compatible API (vLLM)
    elif "together_ai/TA" in llm_model:
        base_url = "https://api.ohmygpt.com/v1"
    else:
        base_url = None
    start = time.time()
    completion = litellm.completion(
        model=llm_model,
        messages=messages,
        max_tokens=max_token_num,
        n=return_num,
        top_p=top_p,
        temperature=temperature,
        stream=stream,
        tools=tools,
        tool_choice=tool_choice,
        base_url=base_url,
        api_key=api_key,
    )
    record_call(model_name, messages, tools, completion, time.time() - start)
    message_0: Message = completion.choices[0].message
    assert message_0 is not None
    assert isinstance(message_0, Message)
    return [message_0]
