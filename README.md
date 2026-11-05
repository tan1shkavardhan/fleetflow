# FleetFlow

### Real-Time Geospatial Vehicle Tracking & Fleet Management

FleetFlow is a real-time fleet monitoring system designed to track vehicle locations, process telemetry, detect operational disruptions, and visualize fleet activity through an interactive dashboard.

The system combines geospatial indexing, real-time communication, persistent telemetry storage, and rule-based alert detection to provide visibility into fleet operations.

## Overview

FleetFlow simulates a fleet of vehicles transmitting GPS telemetry to a centralized backend. The backend processes location updates, maintains vehicle state, detects operational events, and broadcasts updates to the frontend dashboard.

The dashboard displays vehicle locations, geofences, vehicle status, and operational alerts on an interactive map.

## System Architecture

```text
Vehicle Simulator / GPS Device
             |
             v
      FastAPI Backend
             |
       +-----+------+
       |            |
       v            v
     Redis       PostgreSQL
  Geo / Streams  Telemetry & Data
       |
       v
  WebSocket Gateway
       |
       v
 React + TypeScript Dashboard
       |
       v
  Leaflet / OpenStreetMap
```

## Features

### Real-Time Vehicle Tracking

* Ingest vehicle GPS coordinates and speed.
* Maintain current vehicle locations.
* Broadcast telemetry updates through WebSockets.
* Visualize vehicles on an interactive map.

### Geospatial Monitoring

* Redis Geo-based location indexing.
* Geofence configuration and monitoring.
* Detection of geofence-related events.
* Historical telemetry storage in PostgreSQL.

### Operational Alerts

* Rule-based delay detection using telemetry trends.
* Breakdown event handling.
* Geofence alerts.
* Recovery-related status updates.

### Fleet Dashboard

* Interactive vehicle map.
* Vehicle status and details.
* Real-time alert panel.
* Geofence visualization.
* Live updates through WebSockets.

### Vehicle Simulation

* Simulate multiple vehicles.
* Generate continuous GPS telemetry.
* Test ingestion, tracking, and alert workflows without physical GPS devices.

## Technology Stack

| Component               | Technology                   |
| ----------------------- | ---------------------------- |
| Backend                 | Python, FastAPI              |
| Database                | PostgreSQL                   |
| Geospatial indexing     | Redis Geo                    |
| Telemetry streaming     | Redis Streams                |
| Real-time communication | WebSockets                   |
| Frontend                | React, TypeScript, Vite      |
| Mapping                 | React-Leaflet, OpenStreetMap |
| Infrastructure          | Docker Compose               |

## Repository Structure

```text
FleetFlow/
├── backend/
│   ├── app/
│   │   ├── models/
│   │   ├── routers/
│   │   ├── services/
│   │   └── worker/
│   ├── scripts/
│   ├── simulator/
│   ├── tests/
│   └── requirements.txt
│
├── frontend/
│   ├── src/
│   │   ├── components/
│   │   ├── hooks/
│   │   ├── map/
│   │   ├── pages/
│   │   ├── services/
│   │   └── types/
│   ├── package.json
│   └── vite.config.ts
│
├── docker-compose.yml
├── .gitignore
└── README.md
```

## Getting Started

### Prerequisites

* Python 3.12+
* Node.js and npm
* Docker Desktop
* Git

### 1. Clone the Repository

```bash
git clone https://github.com/tan1shkavardhan/fleetflow.git
cd fleetflow
```

### 2. Configure Environment Variables

Create local environment files using the provided examples.

Backend:

```powershell
cd backend
Copy-Item .env.example .env
```

Frontend, in a separate terminal:

```powershell
cd frontend
Copy-Item .env.example .env
```

Configure database, Redis, API, and WebSocket settings according to the environment examples.

### 3. Start Infrastructure

From the project root:

```powershell
docker compose up -d
```

### 4. Start the Backend

From the backend directory:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Backend API:

`http://127.0.0.1:8000`

Interactive API documentation:

`http://127.0.0.1:8000/docs`

### 5. Start the Frontend

From the frontend directory:

```powershell
npm install
npm run dev
```

Open the Vite development URL printed in the terminal, typically:

`http://localhost:5173`

### 6. Run Demo Telemetry

From the backend directory:

```powershell
python -m scripts.seed_demo
```

Start the vehicle simulator:

```powershell
python -m simulator.driver_simulator --vehicles 10 --interval 2
```

The simulator sends telemetry through the backend ingestion API. Vehicle locations and operational events populate as telemetry is processed.

## API Overview

| Endpoint                     | Purpose                             |
| ---------------------------- | ----------------------------------- |
| `GET /health`                | Backend health check                |
| `GET /vehicles/`             | Retrieve vehicles                   |
| `GET /vehicles/{id}/history` | Retrieve vehicle telemetry history  |
| `POST /telemetry/`           | Ingest vehicle telemetry            |
| `GET /geofences/`            | Retrieve geofences                  |
| `GET /alerts/`               | Retrieve operational alerts         |
| `WS /ws/vehicles`            | Real-time vehicle and event updates |

Additional recovery and optimization endpoints are available in the backend implementation.

Refer to the running Swagger documentation for current request schemas and endpoint details.

## Project Goals

FleetFlow demonstrates the integration of:

* Real-time data ingestion
* Geospatial data processing
* Asynchronous backend services
* WebSocket-based communication
* Distributed telemetry processing
* Interactive map visualization
* Rule-based operational monitoring

## Limitations

* Vehicle movement is simulated and does not currently depend on physical GPS hardware.
* Delay and breakdown detection are rule-based indicators.
* Recovery workflow status updates are simulated and do not represent actual vehicle dispatch.
* OpenStreetMap tiles require an internet connection.
* The project is intended as a development and demonstration system, not a production-ready fleet deployment.

## Future Enhancements

* Integration with physical GPS devices.
* Authentication and role-based access control.
* Advanced route optimization using live traffic data.
* Predictive maintenance and analytics.
* Cloud deployment and horizontal scaling.
* Automated driver and vehicle assignment.

## License

No open-source license has been specified yet.
