# GameDB - Scalable Game Object Database

A FastAPI-based game object database with Redis caching and load balancing support.

## Features

- **PostgreSQL Database**: Persistent storage for game objects
- **Redis Caching**: High-performance caching for frequent reads
- **Load Balancing**: Multiple app instances with Nginx load balancer
- **Docker Compose**: Easy deployment and scaling
- **Health Checks**: Built-in health monitoring

## Architecture

```
┌─────────────┐    ┌─────────────┐    ┌─────────────┐
│   Client    │    │    Nginx    │    │    App1     │
│             ├────┤Load Balancer├────┤   App2      │
│             │    │             │    │   App3      │
└─────────────┘    └─────────────┘    └─────────────┘
                                            │
                   ┌─────────────┐    ┌─────────────┐
                   │    Redis    │    │ PostgreSQL  │
                   │   (Cache)   │    │ (Database)  │
                   └─────────────┘    └─────────────┘
```

## Quick Start

### Using PowerShell (Windows)
```powershell
.\start.ps1
```

### Using Docker Compose directly
```bash
docker-compose up --build -d
```

## API Endpoints

- `GET /health` - Health check endpoint
- `GET /get-objects/` - Retrieve game objects (cached for 60 seconds)
- `POST /add-object/` - Add new game object (invalidates cache)

### Object Schema
```json
{
  "o_type": 1,        // Object type ID
  "o_pos": "x,y,z",   // Position coordinates
  "o_rot": "x,y,z"    // Rotation values
}
```

## Services

- **API**: Load balanced on `localhost:8000`
- **PostgreSQL**: Available on `localhost:5432`
- **Redis**: Available on `localhost:6379`

## Caching Strategy

- GET requests are cached for 60 seconds
- Cache is automatically invalidated when new objects are added
- Graceful fallback when Redis is unavailable

## Testing

Run the caching test (requires `requests` package):
```python
python test_caching.py
```

## Scaling

The application runs 3 FastAPI instances by default. To scale:

1. Add more app services in `docker-compose.yml`
2. Update the Nginx upstream configuration in `nginx.conf`
3. Restart the services

## Monitoring

View logs from all services:
```bash
docker-compose logs -f
```

View logs from specific service:
```bash
docker-compose logs -f app1
docker-compose logs -f nginx
docker-compose logs -f redis
```

## Stopping

```bash
docker-compose down
```
