# Home Assistant integration

Expose pressure metrics via REST sensors (replace host/port/token).

```yaml
# configuration.yaml — REST sensors
rest:
  - resource: http://YOUR_SERVER:8780/api/status
    headers:
      Authorization: !secret migraine_api_token
    scan_interval: 300
    sensor:
      - name: Migraine Pressure Current
        value_template: "{{ value_json.current_hpa }}"
        unit_of_measurement: "hPa"
      - name: Migraine Tracker Heartbeat Age
        value_template: "{{ value_json.heartbeat_age_seconds }}"
        unit_of_measurement: "s"
      - name: Migraine Drop Alert Active
        value_template: "{{ value_json.drop_alert_active }}"
```

If `API_TOKEN` is empty and `REQUIRE_API_TOKEN=false`, omit the `Authorization` header.

Optional `command_line` sensor for CSV export path is not needed; use the status endpoint for automations (e.g. notify when `drop_alert_active` turns true).
