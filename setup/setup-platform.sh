#!/bin/bash

set -e

echo "Creating project structure..."

mkdir -p platform/k8s
cd platform/k8s

############################################
# OLLAMA
############################################

cat <<EOF > ollama.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: ollama
spec:
  replicas: 1
  selector:
    matchLabels:
      app: ollama
  template:
    metadata:
      labels:
        app: ollama
    spec:
      containers:
      - name: ollama
        image: ollama/ollama:latest
        ports:
        - containerPort: 11434
        volumeMounts:
        - name: ollama-models
          mountPath: /root/.ollama/models
        resources:
          requests:
            cpu: "2"
            memory: "4Gi"
          limits:
            cpu: "4"
            memory: "8Gi"
      volumes:
      - name: ollama-models
        hostPath:
          path: /models
          type: Directory
---
apiVersion: v1
kind: Service
metadata:
  name: ollama-service
spec:
  type: NodePort
  selector:
    app: ollama
  ports:
  - port: 11434
    targetPort: 11434
    nodePort: 30080
EOF

############################################
# VICTORIAMETRICS
############################################

cat <<EOF > vmetrics.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: victoriametrics
spec:
  replicas: 1
  selector:
    matchLabels:
      app: victoriametrics
  template:
    metadata:
      labels:
        app: victoriametrics
    spec:
      containers:
      - name: victoriametrics
        image: victoriametrics/victoria-metrics:latest
        args:
          - "--storageDataPath=/storage"
          - "--httpListenAddr=:8428"
        ports:
        - containerPort: 8428
        volumeMounts:
        - mountPath: /storage
          name: vm-storage
      volumes:
      - name: vm-storage
        emptyDir: {}
---
apiVersion: v1
kind: Service
metadata:
  name: victoriametrics
spec:
  type: NodePort
  selector:
    app: victoriametrics
  ports:
  - port: 8428
    targetPort: 8428
    nodePort: 30750
EOF

############################################
# GRAFANA
############################################

cat <<EOF > grafana.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: grafana
spec:
  replicas: 1
  selector:
    matchLabels:
      app: grafana
  template:
    metadata:
      labels:
        app: grafana
    spec:
      containers:
      - name: grafana
        image: grafana/grafana:latest
        ports:
        - containerPort: 3000
---
apiVersion: v1
kind: Service
metadata:
  name: grafana-service
spec:
  type: NodePort
  selector:
    app: grafana
  ports:
  - port: 3000
    targetPort: 3000
    nodePort: 30300
EOF

############################################
# LOKI
############################################

cat <<EOF > loki.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: loki
spec:
  replicas: 1
  selector:
    matchLabels:
      app: loki
  template:
    metadata:
      labels:
        app: loki
    spec:
      containers:
      - name: loki
        image: grafana/loki:2.9.3
        args:
        - -config.file=/etc/loki/local-config.yaml
        ports:
        - containerPort: 3100
---
apiVersion: v1
kind: Service
metadata:
  name: loki
spec:
  type: NodePort
  selector:
    app: loki
  ports:
  - port: 3100
    targetPort: 3100
    nodePort: 30100
EOF

############################################
# TEMPO CONFIG
############################################

cat <<EOF > tempo-config.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: tempo-config
data:
  tempo.yaml: |
    server:
      http_listen_port: 3200
    distributor:
      receivers:
        otlp:
          protocols:
            grpc:
            http:
    ingester:
      trace_idle_period: 10s
      max_block_bytes: 1000000
      max_block_duration: 5m
    compactor:
      compaction:
        block_retention: 1h
    storage:
      trace:
        backend: local
        local:
          path: /tmp/tempo
EOF

############################################
# TEMPO
############################################

cat <<EOF > tempo.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: tempo
spec:
  replicas: 1
  selector:
    matchLabels:
      app: tempo
  template:
    metadata:
      labels:
        app: tempo
    spec:
      containers:
      - name: tempo
        image: grafana/tempo:2.4.1
        args:
        - "-config.file=/etc/tempo/tempo.yaml"
        ports:
        - containerPort: 3200
        - containerPort: 4317
        volumeMounts:
        - name: tempo-config
          mountPath: /etc/tempo
      volumes:
      - name: tempo-config
        configMap:
          name: tempo-config
---
apiVersion: v1
kind: Service
metadata:
  name: tempo
spec:
  type: NodePort
  selector:
    app: tempo
  ports:
  - name: tempo-http
    port: 3200
    targetPort: 3200
    nodePort: 30200
  - name: tempo-otlp
    port: 4317
    targetPort: 4317
    nodePort: 30417
EOF

############################################
# PROMTAIL
############################################

cat <<EOF > promtail.yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: promtail
  namespace: default
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: promtail
rules:
  - apiGroups: [""]
    resources:
      - pods
      - nodes
      - namespaces
      - services
    verbs:
      - get
      - watch
      - list
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: promtail
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: ClusterRole
  name: promtail
subjects:
  - kind: ServiceAccount
    name: promtail
    namespace: default
---
apiVersion: v1
kind: ConfigMap
metadata:
  name: promtail-config
data:
  promtail.yaml: |
    server:
      http_listen_port: 9080
      grpc_listen_port: 0
    positions:
      filename: /tmp/positions.yaml
    clients:
      - url: http://loki:3100/loki/api/v1/push
    scrape_configs:
      - job_name: kubernetes-containers
        static_configs:
          - targets:
              - localhost
            labels:
              job: kubernetes-containers
              __path__: /var/log/containers/*.log
---
apiVersion: apps/v1
kind: DaemonSet
metadata:
  name: promtail
spec:
  selector:
    matchLabels:
      app: promtail
  template:
    metadata:
      labels:
        app: promtail
    spec:
      serviceAccountName: promtail
      containers:
      - name: promtail
        image: grafana/promtail:2.9.3
        args:
        - -config.file=/etc/promtail/promtail.yaml
        volumeMounts:
        - name: config
          mountPath: /etc/promtail
        - name: containers
          mountPath: /var/log/containers
        - name: varlog
          mountPath: /var/log
      volumes:
      - name: config
        configMap:
          name: promtail-config
      - name: containers
        hostPath:
          path: /var/log/containers
      - name: varlog
        hostPath:
          path: /var/log
EOF

cd ..

echo "Deleting old cluster..."
k3d cluster delete kvoice-cluster || true

echo "Creating cluster..."

k3d cluster create kvoice-cluster \
--agents 1 \
--image rancher/k3s:v1.31.5-k3s1 \
-p "11434:30080@agent:0" \
-p "30300:30300@agent:0" \
-p "30750:30750@agent:0" \
-p "30100:30100@agent:0" \
-p "30200:30200@agent:0" \
-p "30417:30417@agent:0" \
-v /usr/share/ollama/.ollama/models:/models@all

k3d kubeconfig merge kvoice-cluster --kubeconfig-switch-context

echo "Installing Knative..."

kubectl apply -f https://github.com/knative/serving/releases/download/knative-v1.13.1/serving-crds.yaml
kubectl apply -f https://github.com/knative/serving/releases/download/knative-v1.13.1/serving-core.yaml

kubectl wait --for=condition=Ready pods --all -n knative-serving --timeout=300s

echo "Installing Kourier..."

kubectl apply -f https://github.com/knative/net-kourier/releases/download/knative-v1.13.0/kourier.yaml

kubectl patch configmap/config-network \
-n knative-serving \
--type merge \
-p '{"data":{"ingress-class":"kourier.ingress.networking.knative.dev"}}'

echo "Installing cert-manager..."

kubectl apply -f https://github.com/cert-manager/cert-manager/releases/latest/download/cert-manager.yaml

echo "Installing KServe..."

kubectl apply -f https://github.com/kserve/kserve/releases/download/v0.12.0/kserve.yaml

kubectl set image deployment/kserve-controller-manager \
kube-rbac-proxy=quay.io/brancz/kube-rbac-proxy:v0.13.1 \
-n kserve

echo "Installing kube-state-metrics..."

kubectl apply -k https://github.com/kubernetes/kube-state-metrics.git//examples/standard

echo "Deploying observability + AI stack..."

kubectl apply -f k8s/tempo-config.yaml
kubectl apply -f k8s/

echo "Platform Ready"

kubectl get pods -A