"""Skip all ONNX tests in CI where onnxruntime is unavailable.

The directory tests/onnx.skip/ contains tests that require ONNX Runtime.
These are skipped in CI but can be run locally when onnxruntime is installed.
"""
collect_ignore = ["test_*.py"]
