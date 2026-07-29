def test_apply_priorityclass_0026_creates(cli, k8s_client, kubectl_bin, tmp_path):
    manifest = tmp_path / "m.yaml"
    manifest.write_text('apiVersion: scheduling.k8s.io/v1\nkind: PriorityClass\nmetadata:\n  name: apr-0026\nvalue: 1000\ndescription: bulk-generated\n')
    result = cli("apply", "-f", str(manifest))
    assert result.returncode == 0, result.stderr
    assert "apr-0026" in result.stdout
