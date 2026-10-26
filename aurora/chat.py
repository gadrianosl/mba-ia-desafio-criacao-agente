"""Cliente de terminal para validar o Runner antes da implementação HTTP."""
import argparse
import asyncio
import json
from pathlib import Path

from aurora.config import PROJECT_ROOT, load_settings
from aurora.runtime import Runtime


async def run(args):
    settings = load_settings()
    runtime = Runtime(args.directory, settings.gemini_model)
    try:
        if args.command == 'create':
            result = {'session_id': await runtime.create_session(args.apartment)}
        elif args.command == 'message':
            result = await runtime.message(args.session, args.text)
        elif args.command == 'confirm':
            result = await runtime.confirm(args.session, args.id, args.decision == 'approve')
        else:
            result = [event.model_dump(mode='json') for event in (await runtime.session(args.session)).events]
        print(json.dumps(result, ensure_ascii=False, indent=2))
    finally:
        await runtime.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', type=Path, default=PROJECT_ROOT / '.local' / 'runtime')
    commands = parser.add_subparsers(dest='command', required=True)
    create = commands.add_parser('create')
    create.add_argument('apartment')
    message = commands.add_parser('message')
    message.add_argument('session')
    message.add_argument('text')
    confirm = commands.add_parser('confirm')
    confirm.add_argument('session')
    confirm.add_argument('id')
    confirm.add_argument('decision', choices=['approve', 'deny'])
    events = commands.add_parser('events')
    events.add_argument('session')
    asyncio.run(run(parser.parse_args()))


if __name__ == '__main__':
    main()
