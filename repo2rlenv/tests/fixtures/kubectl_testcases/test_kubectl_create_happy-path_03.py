def test_create_secret_generic_from_literal_succeeds(cli, k8s_client, kubectl_bin, tmp_path):
    secret_name = f"sec-cr-hp03-{tmp_path.name.replace('_', '-').lower()[:30]}"
    result = cli("create", "secret", "generic", secret_name, "--from-literal=pw=s3cr3t", "-n", "default")
    assert result.returncode == 0, result.stderr
    secrets = k8s_client.list_namespaced_secret(namespace="default").items
    assert any(s.metadata.name == secret_name for s in secrets)
