def test_get_namespace_0125_output_json(cli, kubectl_bin):
    seed = kubectl_bin(["create", "namespace", "gfna-0125"])
    assert seed.returncode == 0, seed.stderr
    result = cli("get", "namespace", "gfna-0125", "-o", "json")
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() != ""
