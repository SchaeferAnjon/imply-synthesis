from run_iscas85 import parse_compile_output


def test_parse_compile_output_extracts_metrics() -> None:
    text = "\n".join([
        "circuit : c17  (5 inputs, 2 outputs)",
        "abc map : 6 IMPLY + 4 INV",
        "primitive: 10 IMPLY + 4 ZERO",
        "steps   : naive 54  ->  opt 15   (cells 8)",
        "  PASS  abc-mapping == source (formal cec)",
        "sequence: /tmp/c17.seq.txt",
    ])

    metrics = parse_compile_output(text)

    assert metrics["inputs"] == "5"
    assert metrics["outputs"] == "2"
    assert metrics["abc_map"] == "6 IMPLY + 4 INV"
    assert metrics["primitive"] == "10 IMPLY + 4 ZERO"
    assert metrics["naive_steps"] == "54"
    assert metrics["opt_steps"] == "15"
    assert metrics["cells"] == "8"
