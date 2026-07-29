from kubernetes import client


def test_describe_deployment_shows_replicas(cli, k8s_client, kubectl_bin):
    kubectl_bin(["create", "namespace", "desc-dep-hp03"])
    dep = client.V1Deployment(
        metadata=client.V1ObjectMeta(name="d-hp03", namespace="desc-dep-hp03"),
        spec=client.V1DeploymentSpec(
            replicas=2,
            selector=client.V1LabelSelector(match_labels={"app": "d-hp03"}),
            template=client.V1PodTemplateSpec(
                metadata=client.V1ObjectMeta(labels={"app": "d-hp03"}),
                spec=client.V1PodSpec(containers=[client.V1Container(name="c", image="nginx")]),
            ),
        ),
    )
    client.AppsV1Api(k8s_client.api_client).create_namespaced_deployment(namespace="desc-dep-hp03", body=dep)
    result = cli("describe", "deployment", "d-hp03", "-n", "desc-dep-hp03")
    assert result.returncode == 0, result.stderr
    assert "d-hp03" in result.stdout
    assert "Replicas:" in result.stdout
    assert "Selector:" in result.stdout
    read = client.AppsV1Api(k8s_client.api_client).read_namespaced_deployment(name="d-hp03", namespace="desc-dep-hp03")
    assert read.spec.replicas == 2
