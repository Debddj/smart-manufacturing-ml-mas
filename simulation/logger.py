import json

class MASLogger:
    def __init__(self):
        self.logs = []
        self.max_logs = 200

    def log(self, step, level, agent, message, metadata=None):

        if len(self.logs) >= self.max_logs:
            return

        entry = {
            "step": step,
            "level": level,
            "agent": agent,
            "message": message,
            "metadata": metadata or {}
        }

        self.logs.append(entry)

        print(f"[Step {step}] {level:<7} | {agent:<15} | {message}")

    def get_logs(self):
        return self.logs

    def export(self, filename="logs.json"):
        with open(filename, "w") as f:
            json.dump(self.logs, f, indent=4)