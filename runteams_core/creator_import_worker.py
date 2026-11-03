"""Isolated preflight worker. Reads a ZIP, emits metadata, executes no author code."""
import resource
import sys
from pathlib import Path

resource.setrlimit(resource.RLIMIT_CPU, (15, 15))
if sys.platform == 'linux':
    resource.setrlimit(resource.RLIMIT_AS, (768 * 1024 * 1024, 768 * 1024 * 1024))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from runteams_core.creator_contracts import MAX_BYTES, CreatorContractError, canonical
from runteams_core.creator_source_import import inspect_source

# Validation materializes the complete, bounded skill attachments, including
# generated MCPB. The old 1 MiB scratch-file cap rejected valid locked MCP SDK
# libraries. Match the existing source/package byte budget; keep archive,
# aggregate-byte, file-count, CPU and schema limits enforced as before.
resource.setrlimit(resource.RLIMIT_FSIZE, (MAX_BYTES, MAX_BYTES))

try:
    value = inspect_source(sys.stdin.buffer.read(MAX_BYTES + 1024 * 1024 + 1))
except CreatorContractError as error:
    value = {'error': '源码包未通过检查，请修正后重新选择。', 'code': error.code}
except Exception:
    # Keep unexpected packaging failures diagnosable in the private worker's
    # stderr; the public response remains bounded and never exposes internals.
    import traceback
    traceback.print_exc(file=sys.stderr)
    value = {'error': '源码包无法读取，请检查文件格式。', 'code': 'invalid_source_package'}
sys.stdout.buffer.write(canonical(value))
