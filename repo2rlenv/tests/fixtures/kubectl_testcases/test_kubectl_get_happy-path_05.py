from kubernetes import client


def test_get_deployment_by_name_returns_it(cli, k8s_client, kubectl_bin):
    ns = "get-ns-hp05"
    seed = kubectl_bin(["create", "namespace", ns])
    assert seed.returncode == 0, seed.stderr
    dep = client.V1Deployment(
        metadata=client.V1ObjectMeta(name="d-hp05", namespace=ns),
        spec=client.V1DeploymentSpec(
            replicas=1,
            selector=client.V1LabelSelector(match_labels={"app": "d-hp05"}),
            template=client.V1PodTemplateSpec(
                metadata=client.V1ObjectMeta(labels={"app": "d-hp05"}),
                spec=client.V1PodSpec(containers=[client.V1Container(name="c", image="nginx")]),
            ),
        ),
    )
    client.AppsV1Api(k8s_client.api_client).create_namespaced_deployment(namespace=ns, body=dep)
    result = cli("get", "deployment", "d-hp05", "-n", ns)
    assert result.returncode == 0, result.stderr
    assert "d-hp05" in result.stdout
    read = client.AppsV1Api(k8s_client.api_client).read_namespaced_deployment(name="d-hp05", namespace=ns)
    assert read.metadata.name == "d-hp05"
