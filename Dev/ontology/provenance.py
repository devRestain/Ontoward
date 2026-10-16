from __future__ import annotations

import json

from .v5 import digest, write


class EvidenceSets:
    def __init__(self):
        self.sets = {}

    def intern(self, refs):
        refs = tuple(sorted(set(refs)))
        if not refs:
            raise ValueError("Source evidence cannot be empty")
        key = digest(refs)
        self.sets.setdefault(key, refs)
        return key

    def resolve(self, key):
        return self.sets[key]

    def save(self, path):
        refs = sorted({ref for members in self.sets.values() for ref in members})
        index = {ref:n for n,ref in enumerate(refs)}
        write(path, {"version":1, "refs":refs,
            "sets":{key:[index[ref] for ref in members] for key,members in sorted(self.sets.items())}})

    @classmethod
    def load(cls, path):
        raw = json.loads(path.read_text())
        instance = cls()
        for key, indices in raw['sets'].items():
            members = tuple(raw['refs'][n] for n in indices)
            if digest(members) != key or not members:
                raise ValueError("Evidence set identity differs from its source references")
            instance.sets[key] = members
        return instance
