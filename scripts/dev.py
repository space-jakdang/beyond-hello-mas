"""Local development servers; --live requires existing real inputs and credentials."""
import argparse
import os
import subprocess
import time


def environment(live, api_port):
    env = {**os.environ, 'VITE_API_TARGET': f'http://127.0.0.1:{api_port}'}
    if live:
        from backend.app.config import Settings
        from backend.tools.neighborhoods import group_analysis
        from backend.tools.catalog import load_catalog
        settings = Settings(data_mode='local', llm_mode='live', resource_catalog='v3')
        if settings.evaluation_id is not None:
            raise ValueError('dev-live uses the existing local ledger; clear EVALUATION_ID')
        if not all((settings.openai_model, settings.llm_budget_usd,
                    settings.input_usd_per_million, settings.output_usd_per_million, settings.price_version)):
            raise ValueError('dev-live requires model, budget and price configuration')
        if not (settings.gov24_service_key and settings.gov24_service_key.get_secret_value().strip()):
            raise ValueError('dev-live requires GOV24_SERVICE_KEY')
        group_analysis(settings)
        load_catalog(settings.catalog_path)
        env.update(DATA_MODE='local', LLM_MODE='live', RESOURCE_CATALOG='v3')
    return env


def port(value):
    number = int(value)
    if not 1024 <= number <= 65535:
        raise argparse.ArgumentTypeError('port must be between 1024 and 65535')
    return number


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true')
    parser.add_argument('--api-port', type=port, default=8000)
    parser.add_argument('--ui-port', type=port, default=5173)
    args = parser.parse_args()
    if args.api_port == args.ui_port:
        parser.error('API and UI ports must differ')
    env = environment(args.live, args.api_port)
    processes = []
    exit_code = 0
    try:
        processes.append(subprocess.Popen(['uv', 'run', 'uvicorn', 'backend.app.main:create_app', '--factory', '--reload', '--host', '127.0.0.1', '--port', str(args.api_port)], env=env))
        processes.append(subprocess.Popen(['npm', '--prefix', 'frontend', 'run', 'dev', '--', '--port', str(args.ui_port), '--strictPort'], env=env))
        while all(p.poll() is None for p in processes):
            time.sleep(0.2)
        exit_code = next(p.returncode for p in processes if p.returncode is not None)
    except KeyboardInterrupt:
        pass
    finally:
        for p in processes:
            if p.poll() is None:
                p.terminate()
        for p in processes:
            try:
                p.wait(timeout=5)
            except subprocess.TimeoutExpired:
                p.kill()
                p.wait()
    return exit_code


if __name__ == '__main__':
    raise SystemExit(main())
