{{- define "sopiskill.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "sopiskill.fullname" -}}
{{- if .Values.fullnameOverride -}}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- $name := default .Chart.Name .Values.nameOverride -}}
{{- if contains $name .Release.Name -}}
{{- .Release.Name | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}
{{- end -}}

{{- define "sopiskill.labels" -}}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/part-of: sopiskill
{{- end -}}

{{- define "sopiskill.secretName" -}}
{{- if .Values.secrets.existingSecret -}}
{{- .Values.secrets.existingSecret -}}
{{- else -}}
{{- printf "%s-secrets" (include "sopiskill.fullname" .) -}}
{{- end -}}
{{- end -}}

{{- define "sopiskill.pgHost" -}}
{{- printf "%s-pgvector-db" (include "sopiskill.fullname" .) -}}
{{- end -}}

{{- define "sopiskill.redisHost" -}}
{{- printf "%s-redis" (include "sopiskill.fullname" .) -}}
{{- end -}}

{{- define "sopiskill.minioHost" -}}
{{- printf "%s-minio" (include "sopiskill.fullname" .) -}}
{{- end -}}

{{- define "sopiskill.coreApiUrl" -}}
{{- printf "http://%s-core-api:%d" (include "sopiskill.fullname" .) (int .Values.coreApi.port) -}}
{{- end -}}

{{- define "sopiskill.aiApiUrl" -}}
{{- printf "http://%s-ai-api:%d" (include "sopiskill.fullname" .) (int .Values.aiApi.port) -}}
{{- end -}}
