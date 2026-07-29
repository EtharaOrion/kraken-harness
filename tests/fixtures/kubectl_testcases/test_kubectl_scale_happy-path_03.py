from kubernetes import client


def test_scale_statefulset_up_to_two(cli, k8s_client, kubectl_bin):
    kubectl_bin(["create", "namespace", "scale-sts-hp03"])
    sts = client.V1StatefulSet(
        metadata=client.V1ObjectMeta(name="s-hp03", namespace="scale-sts-hp03"),
        spec=client.V1StatefulSetSpec(
            replicas=1,
            service_name="s-hp03-svc",
            selector=client.V1LabelSelector(match_labels={"app": "s-hp03"}),
            template=client.V1PodTemplateSpec(
                metadata=client.V1ObjectMeta(labels={"app": "s-hp03"}),
                spec=client.V1PodSpec(containers=[client.V1Container(name="c", image="nginx")]),
            ),
        ),
    )
    client.AppsV1Api(k8s_client.api_client).create_namespaced_stateful_set(namespace="scale-sts-hp03", body=sts)
    result = cli("scale", "statefulset", "s-hp03", "--replicas=2", "-n", "scale-sts-hp03")
    assert result.returncode == 0, result.stderr
    assert "scaled" in result.stdout.lower()
    read = client.AppsV1Api(k8s_client.api_client).read_namespaced_stateful_set(name="s-hp03", namespace="scale-sts-hp03")
    assert read.spec.replicas == 2
