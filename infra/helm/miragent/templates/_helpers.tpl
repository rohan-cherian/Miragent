{{/*
Expand the name of the chart.
*/}}
{{- define "miragent.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully qualified app name.
Truncate at 63 chars because some Kubernetes name fields are limited to this.
*/}}
{{- define "miragent.fullname" -}}
{{- printf "%s-miragent" .Release.Name | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create chart label value (chart name + version).
*/}}
{{- define "miragent.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Common labels applied to all resources.
*/}}
{{- define "miragent.labels" -}}
helm.sh/chart: {{ include "miragent.chart" . }}
app.kubernetes.io/name: {{ include "miragent.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{/*
Selector labels (subset of common labels used for pod selectors).
*/}}
{{- define "miragent.selectorLabels" -}}
app.kubernetes.io/name: {{ include "miragent.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
ServiceAccount name — uses a default based on the fullname if not overridden.
*/}}
{{- define "miragent.serviceAccountName" -}}
{{- if .Values.serviceAccount -}}
  {{- if .Values.serviceAccount.name -}}
    {{- .Values.serviceAccount.name }}
  {{- else -}}
    {{- include "miragent.fullname" . }}
  {{- end }}
{{- else -}}
  {{- include "miragent.fullname" . }}
{{- end }}
{{- end }}

{{/*
Build the full API image path:
  <global.imageRegistry>/<api.image.repository>:<api.image.tag>
If imageRegistry is empty, omit the registry prefix.
*/}}
{{- define "miragent.apiImage" -}}
{{- $registry := .Values.global.imageRegistry -}}
{{- $repo := .Values.api.image.repository -}}
{{- $tag := .Values.api.image.tag | default .Chart.AppVersion -}}
{{- if $registry -}}
  {{- printf "%s/%s:%s" $registry $repo $tag }}
{{- else -}}
  {{- printf "%s:%s" $repo $tag }}
{{- end }}
{{- end }}

{{/*
Build the full worker image path:
  <global.imageRegistry>/<worker.image.repository>:<worker.image.tag>
If imageRegistry is empty, omit the registry prefix.
*/}}
{{- define "miragent.workerImage" -}}
{{- $registry := .Values.global.imageRegistry -}}
{{- $repo := .Values.worker.image.repository -}}
{{- $tag := .Values.worker.image.tag | default .Chart.AppVersion -}}
{{- if $registry -}}
  {{- printf "%s/%s:%s" $registry $repo $tag }}
{{- else -}}
  {{- printf "%s:%s" $repo $tag }}
{{- end }}
{{- end }}
