"""Shared serial call and wall-time caps; checked before every billable action."""
import time
from policytrace.harness.context import HarnessError


class RunBudget:
    def __init__(self, max_calls, max_seconds):
        self.max_calls, self.max_seconds = max_calls, max_seconds
        self.calls, self.started = 0, time.monotonic()

    def check(self):
        if time.monotonic()-self.started >= self.max_seconds:
            raise HarnessError('wall_time_cap_reached')

    def take(self):
        self.check()
        if self.calls >= self.max_calls:
            raise HarnessError('total_model_call_cap_reached')
        self.calls += 1


class BudgetedStudent:
    def __init__(self, client, budget):
        self.client, self.budget = client, budget

    def __getattr__(self, name):
        return getattr(self.client, name)

    def generate(self, request):
        self.budget.take()
        return self.client.generate(request)
