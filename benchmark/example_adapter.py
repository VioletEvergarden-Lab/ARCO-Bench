"""Example for a different JSON API. Select benchmark.example_adapter:Adapter.

POST /generate receives {model, messages, options}; its response is
{model, answer, done, usage}. Adapt these two methods to your service's schema.
The common runner still handles credentials, durable requests and scoring.
"""
from benchmark.adapters import ChatCompletions, Completion


class Adapter(ChatCompletions):
    def build(self, messages, config):
        return '/generate', {'model': config['model'], 'messages': messages, 'options': config['parameters']}

    def parse(self, obj):
        text = obj.get('answer', '')
        return Completion(text if isinstance(text, str) else '', 'completed' if obj.get('done') else 'failed',
                          obj.get('model'), usage=obj.get('usage') or {})
