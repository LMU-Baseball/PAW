"""The Dash HTML shell. The Dash page does not extend base.html, so the site's
grey+palms background and lion favicon are set here (hardcoded — cannot use
base.html CSS tokens; keep in sync with the site brand). See memory §3c."""

INDEX_STRING = """<!DOCTYPE html>
<html>
<head>
{%metas%}
<title>{%title%}</title>
<link rel="icon" type="image/png" href="/static/reports/lion.png">
{%css%}
<style>
  body {
    margin: 0; min-height: 100vh;
    background-color: #f5f5f5;
    background-image: url('/static/brand/palms-grey.png');
    background-repeat: no-repeat; background-position: center bottom;
    background-size: cover; background-attachment: fixed;
    font-family: 'Teko', sans-serif;
  }
</style>
</head>
<body>
{%app_entry%}
<footer>{%config%}{%scripts%}{%renderer%}</footer>
</body>
</html>"""
