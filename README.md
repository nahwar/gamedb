# GameDB

A high-performance, scalable game data storage system built with FastAPI, PostgreSQL, and Redis. Designed for asynchronous multiplayer game mechanics similar to those found in Death Stranding, Dark Souls, and other games featuring indirect player interactions.

## Overview

GameDB provides a production-ready REST API for managing asynchronous multiplayer game data including player-placed objects, messages, and phantom recordings. The system is designed to enable indirect multiplayer experiences where players can leave traces of their actions for others to discover, without requiring real-time synchronization.

The system utilizes Redis for caching with gzip compression, async PostgreSQL for persistence, and Nginx for load balancing across multiple application instances.

## Use Cases

- **Player-placed Objects**: Share items, structures, or markers that persist in other players' worlds
- **Asynchronous Messages**: Leave hints, warnings, or notes for other players (like Dark Souls messages)
- **Phantom Recordings**: Store player action sequences that can be replayed as ghostly apparitions
- **Shared World State**: Enable collaborative world-building without direct player interaction
- **Cross-session Persistence**: Maintain player contributions across game sessions and updates

## Key Features

- **Asynchronous Architecture**: Built on FastAPI with async/await patterns for high concurrency
- **Intelligent Caching**: Redis-based caching with gzip compression reduces bandwidth and improves response times
- **Horizontal Scaling**: Load-balanced architecture with Nginx supporting multiple application instances
- **Connection Pooling**: Optimized PostgreSQL connection management for better resource utilization
- **Health Monitoring**: Built-in health check endpoints for service monitoring
- **Type Safety**: Pydantic models with validation for data integrity
- **Automatic Schema Management**: Database tables created automatically on startup
- **Performance Testing**: Included Locust configuration for load testing

## Architecture

```
Client Requests
      |
      v
┌─────────────────┐
│  Nginx (Port 80)│  Load Balancer
└────────┬────────┘
         |
    ┌────┴────┐
    |         |
    v         v
┌──────┐  ┌──────┐
│ App1 │  │ App2 │  FastAPI Instances
└──┬───┘  └──┬───┘
   |         |
   └────┬────┘
        |
   ┌────┴─────┐
   |          |
   v          v
┌──────┐  ┌──────────┐
│Redis │  │PostgreSQL│
│Cache │  │ Database │
└──────┘  └──────────┘
```

## Prerequisites

- Docker and Docker Compose
- Python 3.10+ (for local development)

## Quick Start

### Using Docker Compose

```bash
docker-compose up --build -d
```

The API will be available at `http://localhost:8000`

### Stopping Services

```bash
docker-compose down
```

To remove volumes (database data):

```bash
docker-compose down -v
```

## API Documentation

Once running, interactive API documentation is available at:
- Swagger UI: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`

### Endpoints

#### Health Check
```
GET /health
```
Returns service health status.

**Response:**
```json
{
  "status": "healthy"
}
```

#### Retrieve Game Data
```
GET /get-objects
```
Retrieves the most recent game data including objects, messages, and phantoms. Response is cached for 30 seconds and compressed with gzip.

**Response:** (gzip compressed JSON)
```json
{
  "objects": [...],    // Last 200 objects
  "messages": [...],   // Last 200 messages
  "phantoms": [...]    // Last 20 phantoms
}
```

#### Store Game Data
```
POST /add-object
```
Stores new game data including object, message, and phantom information.

**Request Body:**
```json
{
  "obj": {
    "u_uuid": "user-uuid",
    "o_type": 1,
    "o_pos": "10.5,20.0,30.2",
    "o_rot": "0.0,90.0,0.0"
  },
  "message": {
    "u_uuid": "user-uuid",
    "part1": "message text part 1",
    "part2": "message text part 2",
    "part3": "message text part 3"
  },
  "phantom": {
    "u_uuid": "user-uuid",
    "data": [
      ["pos1", "rot1"],
      ["pos2", "rot2"]
    ]
  }
}
```

**Note:** At least one of `obj` or `message` must be provided. `phantom` is required.

## Data Models

### Object
Represents a game object with position and rotation.

| Field   | Type   | Description                          |
|---------|--------|--------------------------------------|
| id      | int    | Auto-generated primary key           |
| u_uuid  | string | User identifier                      |
| o_type  | int    | Object type identifier               |
| o_pos   | string | Position coordinates (x,y,z format)  |
| o_rot   | string | Rotation values (x,y,z format)       |

### Message
Stores user messages in three parts.

| Field   | Type   | Description                    |
|---------|--------|--------------------------------|
| id      | int    | Auto-generated primary key     |
| u_uuid  | string | User identifier                |
| part1   | string | Message part 1                 |
| part2   | string | Message part 2                 |
| part3   | string | Message part 3                 |

### Phantom
Stores phantom data as JSON arrays for recording player movement sequences.

| Field   | Type            | Description                                      |
|---------|-----------------|--------------------------------------------------|
| id      | int             | Auto-generated primary key                       |
| u_uuid  | string          | User identifier                                  |
| data    | array of arrays | Phantom position/rotation recording data         |

**Example Use Case**: Record a player's movement path through a level, which can later be replayed as a ghost or phantom for other players to see, similar to Dark Souls bloodstains or Death Stranding's other player traces.

## Configuration

### Environment Variables

The following environment variables can be configured in `docker-compose.yml`:

| Variable      | Default Value                                          | Description                |
|---------------|--------------------------------------------------------|----------------------------|
| DATABASE_URL  | `postgresql://username:password@db:5432/gamedb`       | PostgreSQL connection URL  |
| REDIS_URL     | `redis://redis:6379`                                   | Redis connection URL       |

### Cache Configuration

Cache duration can be adjusted in `main.py`:

```python
CACHE_DURATION = 30  # Cache duration in seconds
```

### Database Tuning

PostgreSQL is configured with optimized settings in `docker-compose.yml` for better performance:
- Max connections: 150
- Shared buffers: 512MB
- Effective cache size: 1.5GB

## Performance Testing

The project includes a Locust configuration for load testing.

### Install Locust

```bash
pip install locust
```

### Run Load Tests

```bash
locust -f locustfile.py --host=http://localhost:8000
```

Then open `http://localhost:8089` in your browser to configure and start the test.

## Scaling

The default configuration runs 2 application instances. To scale horizontally:

1. Add more app services in `docker-compose.yml`:
```yaml
app3:
  image: mygameapp:latest
  environment:
    DATABASE_URL: postgresql://username:password@db:5432/gamedb
    REDIS_URL: redis://redis:6379
  depends_on:
    db:
      condition: service_healthy
    redis:
      condition: service_healthy
```

2. Update `nginx.conf` to include the new instance:
```nginx
upstream gamedb_backend {
    server app1:8000;
    server app2:8000;
    server app3:8000;
}
```

3. Restart services:
```bash
docker-compose up --build -d
```

## Development

### Local Setup

1. Install dependencies using uv:
```bash
pip install uv
uv sync
```

2. Start PostgreSQL and Redis:
```bash
docker-compose up db redis -d
```

3. Run the application:
```bash
uvicorn main:app --reload
```

### Project Structure

```
gamedb/
├── main.py              # FastAPI application
├── locustfile.py        # Load testing configuration
├── docker-compose.yml   # Docker services configuration
├── Dockerfile           # Multi-stage build for production
├── nginx.conf           # Nginx load balancer configuration
├── pyproject.toml       # Python dependencies
└── uv.lock             # Dependency lock file
```

## Monitoring and Logging

### View All Logs
```bash
docker-compose logs -f
```

### View Specific Service Logs
```bash
docker-compose logs -f app1
docker-compose logs -f nginx
docker-compose logs -f db
docker-compose logs -f redis
```

### Service Ports

| Service    | Port | Description              |
|------------|------|--------------------------|
| Nginx      | 8000 | Load balancer / API      |
| PostgreSQL | 5432 | Database (external)      |
| Redis      | 6379 | Cache (external)         |

## Optimization Features

- **Connection Pooling**: Both PostgreSQL and Redis use connection pools to manage resources efficiently
- **Async Database Operations**: Non-blocking I/O for database queries
- **Gzip Compression**: Responses are compressed to reduce bandwidth usage
- **orjson Serialization**: Fast JSON serialization/deserialization
- **Optimized Queries**: Limited result sets (200 objects, 200 messages, 20 phantoms)
- **Strategic Caching**: 30-second cache duration balances freshness with performance

## License

This project is available as open source under the terms of the MIT License.

## Contributing

Contributions are welcome. Please open an issue or submit a pull request for any improvements or bug fixes.
