def test_get_namespace_0126_output_wide(cli, kubectl_bin):
    seed = kubectl_bin(["create", "namespace", "gfna-0126"])
    assert seed.returncode == 0, seed.stderr
    result = cli("get", "namespace", "gfna-0126", "-o", "wide")
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() != ""
