import subprocess
import sys


def test_importing_cli_and_service_pulls_no_engine_modules():
    code = (
        "import sys\n"
        "import docsift.cli.main\n"
        "import docsift.services.conversion_service\n"
        "import docsift.services.comparison_service\n"
        "import docsift.services.inspection_service\n"
        "import docsift.api.app\n"
        "import docsift.services.job_service\n"
        "banned = {'docling', 'markitdown', 'torch', 'transformers'}\n"
        "loaded = {m.split('.')[0] for m in sys.modules}\n"
        "sys.exit(1 if banned & loaded else 0)\n"
    )
    result = subprocess.run([sys.executable, "-c", code], capture_output=True)
    assert result.returncode == 0, result.stderr.decode()
