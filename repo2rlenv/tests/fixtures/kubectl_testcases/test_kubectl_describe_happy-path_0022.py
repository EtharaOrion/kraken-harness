def test_describe_namespace_0022_by_name(cli, kubectl_bin):
    seed = kubectl_bin(["create", "namespace", "ena-0022"])
    assert seed.returncode == 0, seed.stderr
    result = cli("describe", "namespace", "ena-0022")
    assert result.returncode == 0, result.stderr
    assert "ena-0022" in result.stdout
    assert "Status:" in result.stdout or "Labels:" in result.stdout
