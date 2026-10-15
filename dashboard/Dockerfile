# Runtime only: the repository is mounted at /app, so `git pull` + restart updates the
# code, and the dashboard always reads the restosuite.db that the daily export writes.
#   docker build -t restosuite-dashboard -f dashboard/Dockerfile .
FROM python:3.12-slim
COPY requirements.txt /tmp/requirements.txt
COPY dashboard/requirements.txt /tmp/dashboard-requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt -r /tmp/dashboard-requirements.txt
WORKDIR /app
EXPOSE 5021
CMD ["gunicorn", "--preload", "--workers", "2", "--bind", "0.0.0.0:5021", "--access-logfile", "-", "dashboard.app:app"]
