import subprocess
import time

if __name__ == "__main__":
    processes = []
    exit_code = 0
    try:
        processes.append(subprocess.Popen(["uv", "run", "uvicorn", "backend.app.main:create_app", "--factory", "--reload", "--host", "127.0.0.1"]))
        processes.append(subprocess.Popen(["npm", "--prefix", "frontend", "run", "dev"]))
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
    raise SystemExit(exit_code)
