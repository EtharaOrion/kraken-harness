def test_get_priorityclass_0159_output_custom(cli, kubectl_bin, tmp_path):
    manifest = tmp_path / "m.yaml"
    manifest.write_text('apiVersion: scheduling.k8s.io/v1\nkind: PriorityClass\nmetadata:\n  name: gfpr-0159\nvalue: 1000\ndescription: bulk-generated\n')
    seed = kubectl_bin(["apply", "-f", str(manifest)])
    assert seed.returncode == 0, seed.stderr
    result = cli("get", "priorityclass", "gfpr-0159", "-n", "default", "-o", "custom-columns=NAME:.metadata.name")
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() != ""
