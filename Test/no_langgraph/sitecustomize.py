"""Make LangGraph unavailable in explicitly guarded offline verification processes."""
import sys


class NoLangGraph:
    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'langgraph' or fullname.startswith('langgraph.'):
            raise ImportError('LangGraph is unavailable in this acceptance process')
        return None


sys.meta_path.insert(0, NoLangGraph())
