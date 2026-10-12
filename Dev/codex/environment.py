import argparse
import json
import os
import subprocess
import tomllib
from pathlib import Path
from uuid import UUID


STATE_HOME = Path('/opt/ontology/codex-state')
DEFAULTS = {
    'forced_login_method': 'chatgpt',
    'cli_auth_credentials_store': 'file',
    'model': 'gpt-6-luna',
    'model_reasoning_effort': 'medium',
    'web_search': 'disabled',
    'sandbox_mode': 'read-only',
    'approval_policy': 'never',
}


def configuration():
    if Path(os.environ.get('CODEX_HOME', '')) != STATE_HOME:
        raise ValueError('Run inside the ontology-extraction service with its dedicated CODEX_HOME')
    STATE_HOME.mkdir(parents=True, exist_ok=True, mode=0o700)
    STATE_HOME.chmod(0o700)
    path = STATE_HOME / 'config.toml'
    settings = tomllib.loads(path.read_text()) if path.exists() else {}
    return path, settings


def write_configuration(path, settings):
    unknown = settings.keys() - DEFAULTS.keys() - {'forced_chatgpt_workspace_id'}
    if unknown:
        raise ValueError('Preserve existing custom configuration; reconcile it before setup')
    text = '\n'.join(f'{key} = {json.dumps(value)}' for key, value in settings.items()) + '\n'
    temporary = path.with_suffix('.tmp')
    temporary.write_text(text)
    temporary.chmod(0o600)
    temporary.replace(path)


def main():
    parser = argparse.ArgumentParser(description='Initialize and inspect isolated Codex configuration without exposing credentials')
    parser.add_argument('action', choices=['init', 'status', 'pin-workspace'])
    parser.add_argument('workspace_uuid', nargs='?')
    args = parser.parse_args()
    try:
        path, settings = configuration()
        if args.action == 'init':
            settings.update(DEFAULTS)
            write_configuration(path, settings)
            print('Initialize ChatGPT-only Codex configuration; workspace pin still requires the confirmed SNU UUID')
        elif args.action == 'pin-workspace':
            if not args.workspace_uuid:
                raise ValueError('Supply the confirmed SNU workspace UUID')
            workspace = UUID(args.workspace_uuid)
            if workspace.int == 0:
                raise ValueError('Reject the placeholder UUID')
            settings.update(DEFAULTS)
            settings['forced_chatgpt_workspace_id'] = str(workspace)
            write_configuration(path, settings)
            print('Pin the confirmed SNU workspace UUID; verify login before extraction')
        else:
            result = subprocess.run(['codex', 'login', 'status'], capture_output=True, text=True, check=False)
            mode = 'chatgpt' if result.returncode == 0 and 'chatgpt' in (result.stdout + result.stderr).lower() else 'not_verified'
            print(json.dumps({
                'codex_home': str(STATE_HOME),
                'authentication': mode,
                'workspace_pin_configured': bool(settings.get('forced_chatgpt_workspace_id')),
                'model': settings.get('model'),
                'reasoning': settings.get('model_reasoning_effort'),
                'web_search': settings.get('web_search'),
                'ready_for_model_probe': mode == 'chatgpt' and bool(settings.get('forced_chatgpt_workspace_id')),
            }, indent=2))
    except (ValueError, OSError, tomllib.TOMLDecodeError) as error:
        parser.exit(2, f'{error}\n')


if __name__ == '__main__':
    main()
