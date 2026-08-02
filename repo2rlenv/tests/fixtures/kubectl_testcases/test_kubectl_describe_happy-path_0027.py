def test_describe_priorityclass_0027_by_name(cli, kubectl_bin, tmp_path):
    manifest = tmp_path / "m.yaml"
    manifest.write_text('apiVersion: scheduling.k8s.io/v1\nkind: PriorityClass\nmetadata:\n  name: epr-0027\nvalue: 1000\ndescription: bulk-generated\n')
    seed = kubectl_bin(["apply", "-f", str(manifest)])
    assert seed.returncode == 0, seed.stderr
    result = cli("describe", "priorityclass", "epr-0027", "-n", "default")
    assert result.returncode == 0, result.stderr
    assert "epr-0027" in result.stdout
