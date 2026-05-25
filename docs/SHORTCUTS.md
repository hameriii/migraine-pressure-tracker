# Apple Shortcuts — log migraine

1. Add action **Get Contents of URL**
2. URL: `http://YOUR_SERVER:8780/api/migraines`
3. Method: **POST**
4. Headers: `Content-Type: application/json`  
   If using a token: `Authorization: Bearer YOUR_API_TOKEN`
5. Request body (JSON):

```json
{
  "time": "{{current date ISO}}",
  "note": "Logged from Shortcuts"
}
```

The response includes `correlation.summary` describing pressure change before the event.

Subscribe to the same ntfy topic as the tracker for pressure alerts.
