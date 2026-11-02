"""Small protocol adapters; task construction and evaluation remain independent."""
from dataclasses import dataclass, field
from urllib.parse import quote
import copy
import importlib


@dataclass
class Completion:
    text: str = ''
    status: str = 'failed'
    model: str | None = None
    response_id: str | None = None
    usage: dict = field(default_factory=dict)
    tool_call: bool = False


class ChatCompletions:
    """Non-streaming /chat/completions, including compatible hosted/local APIs."""
    def build(self, messages, config):
        return '/chat/completions', dict(copy.deepcopy(config['parameters']), model=config['model'], messages=messages)

    def headers(self, key):
        return {'Authorization': 'Bearer ' + key} if key else {}

    def parse(self, obj):
        choices = obj.get('choices') or []
        if len(choices) != 1:
            return Completion(status='invalid_envelope', model=obj.get('model'))
        choice = choices[0]; message = choice.get('message') or {}
        text = message.get('content') or ''
        if isinstance(text, list):
            text = ''.join(p.get('text', '') for p in text if p.get('type') in ('text', 'output_text'))
        if not isinstance(text, str):
            return Completion(status='invalid_envelope', model=obj.get('model'))
        state = choice.get('finish_reason')
        if state not in ('stop', 'length', 'content_filter', 'tool_calls', 'function_call'):
            return Completion(status='invalid_envelope', model=obj.get('model'))
        return Completion(text, 'completed' if state == 'stop' else 'truncated' if state == 'length' else 'refused',
                          obj.get('model'), obj.get('id'), obj.get('usage') or {},
                          bool(message.get('tool_calls') or message.get('function_call')))

    def poll_path(self, response_id):
        return None


class Responses(ChatCompletions):
    """Responses API with durable response IDs and GET-only polling on resume."""
    def build(self, messages, config):
        return '/responses', dict(copy.deepcopy(config['parameters']), model=config['model'], input=messages)

    def parse(self, obj):
        output = obj.get('output') or []
        text = ''.join(p.get('text', '') for m in output if m.get('type') == 'message'
                       for p in m.get('content', []) if p.get('type') in ('text', 'output_text'))
        return Completion(text, obj.get('status', 'invalid_envelope'), obj.get('model'), obj.get('id'),
                          obj.get('usage') or {}, any(m.get('type') not in ('message', 'reasoning') for m in output))

    def poll_path(self, response_id):
        if not isinstance(response_id, str) or not response_id:
            raise ValueError('Missing accepted response ID')
        return '/responses/' + quote(response_id, safe='')


def load(name):
    if name == 'chat_completions':
        return ChatCompletions()
    if name == 'responses':
        return Responses()
    module, sep, cls = name.partition(':')
    if not sep or not module or not cls:
        raise ValueError('Adapter must be chat_completions, responses, or module:Class')
    adapter = getattr(importlib.import_module(module), cls)()
    if not all(callable(getattr(adapter, m, None)) for m in ('build', 'headers', 'parse', 'poll_path')):
        raise ValueError('Adapter does not implement build/headers/parse/poll_path')
    return adapter
