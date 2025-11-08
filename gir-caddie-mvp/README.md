# GIR Caddie MVP

An AI-powered golf caddie system that helps golfers plan their shots by analyzing course layouts, player profiles, and hazards. The system uses GPT-4o vision to extract information from scorecards and hole layouts, then generates strategic shot plans to maximize Green In Regulation (GIR) probability.

## Features

- **Player Profile Management**: Input your club yardages and dispersion patterns with an intuitive form-based UI
- **Scorecard Extraction**: Upload a scorecard image and automatically extract course information, tee boxes, and yardages
- **Hole Layout Analysis**: Upload hole images (single hole or full course map) to identify hazards and calculate yardages
- **Directional Correction**: Correct hazard directions (left/right) and recalibrate for improved accuracy
- **AI-Powered Shot Planning**: Get strategic shot recommendations based on your profile, course layout, and hazards
- **Tee Box Integration**: Automatically populate yardages from parsed scorecard data

## Architecture

The application consists of:

- **Backend (FastAPI)**: REST API endpoints for processing images and generating shot plans
- **Frontend (HTML/JavaScript)**: Single-page web interface for user interaction
- **AI Processing**: Uses OpenAI GPT-4o for:
  - Scorecard image parsing
  - Hole layout and hazard detection
  - Strategic shot planning

## Prerequisites

- Docker and Docker Compose
- OpenAI API key

## Setup

1. **Navigate to the project directory**:
   ```bash
   cd gir-caddie-mvp
   ```

2. **Create a `.env` file**:
   ```bash
   echo "OPENAI_API_KEY=your_openai_api_key_here" > .env
   ```
   
   Replace `your_openai_api_key_here` with your actual OpenAI API key.

3. **Build and start the service**:
   ```bash
   docker compose up -d --build
   ```

4. **Access the application**:
   - Web Interface: http://localhost:8011

## Usage

The application follows a 4-step workflow:

### 1) Player Profile (Yardages & Dispersion)

Enter your golf club information:
- **Player ID**: Your identifier
- **Clubs**: For each club, enter:
  - Club name (e.g., Driver, 7i, PW)
  - Carry distance (yards)
  - Standard deviation left/right
  - Standard deviation long
  - Standard deviation short
- **Miss Bias** (optional): Describe your typical miss patterns

Click "Save Profile" to store your data.

### 2) Scorecard → JSON

Upload a scorecard image. The AI will extract:
- Course name
- Available tee boxes (Blue, White, Red, etc.)
- Hole numbers, par, and yardages for each tee box

The parsed data is displayed in a formatted table and stored for use in step 3.

### 3) Hole Layout → Hazards JSON

Upload a hole layout image (single hole or full course map):
- **Hole Number**: Enter the hole you want to analyze
- **Tee Box**: Select from the dropdown (populated from parsed scorecard)
- **Tee Yardage**: Automatically filled from scorecard data
- **Hole Layout Image**: Upload the image

The AI will:
- Identify the tee and green positions
- Detect hazards (water, bunkers, out of bounds)
- Calculate yardages to each hazard
- Display hazards with editable direction selectors

**Recalibration**: If the AI misidentifies hazard directions (left/right), you can:
1. Select the correct direction from the dropdown for each hazard
2. Click "Recalibrate with Corrections" to re-analyze with your corrections

### 4) Plan Hole (Model Chooses Clubs)

Generate a strategic shot plan:
- **Hole Number**: The hole to plan
- **Tee Box**: Which tee you're playing from

The AI will generate:
- Recommended shots with club selection
- Aim points and intended carry distances
- Expected leave distances
- Risk assessment
- Estimated GIR probability

## API Endpoints

- `GET /` - Main web interface
- `POST /api/profile` - Save player profile
  ```json
  {
    "player_id": "user",
    "clubs": [
      {"club": "Driver", "carry": 255, "std_lr": 15, "std_long": 10, "std_short": 10}
    ],
    "miss_bias": {"driver": "slight left"}
  }
  ```

- `POST /api/parse-scorecard` - Extract scorecard data from image
  - Form data: `scorecard_image` (file)
  - Returns: Course name, tees, holes with yardages

- `POST /api/extract-hole-layout` - Analyze hole layout and hazards
  - Form data: `hole_image` (file), `hole_num` (int), `tee_yardage` (int)
  - Returns: Tee/green positions, pixel_per_yard, hazards with yardages

- `POST /api/recalibrate-hole-layout` - Re-analyze with directional corrections
  - Form data: `hole_image` (file), `hole_num` (int), `tee_yardage` (int), `hazard_corrections` (JSON)
  - Returns: Updated layout analysis

- `POST /api/plan-hole` - Generate shot plan
  ```json
  {
    "hole_num": 1,
    "tee_box": "Blue"
  }
  ```
  - Returns: Strategic shot plan with club recommendations

## Project Structure

```
gir-caddie-mvp/
├── app.py                 # FastAPI application and API endpoints
├── static/
│   └── index.html        # Web interface
├── uploads/              # Generated data files (gitignored)
│   ├── player_profile.json
│   ├── scorecard.json
│   └── hole_*_layout.json
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── .dockerignore
└── README.md
```

## Technology Stack

- **Backend**: FastAPI, Python 3.11
- **Frontend**: HTML5, JavaScript (vanilla)
- **AI/ML**: OpenAI API
  - Vision: GPT-4o for image analysis
  - Chat: GPT-4o for strategic planning
- **Containerization**: Docker, Docker Compose

## Environment Variables

Create a `.env` file in the project root:

```env
OPENAI_API_KEY=your_openai_api_key_here
```

The `.env` file is gitignored and should never be committed to the repository.

## Development

### Rebuilding the Service

After code changes:
```bash
docker compose up -d --build
```

### Viewing Logs

```bash
# All services
docker compose logs -f

# Specific service
docker compose logs -f web
```

### Stopping Services

```bash
docker compose down
```

To also remove volumes:
```bash
docker compose down -v
```

## How It Works

1. **Player Profile**: Stores your club distances and dispersion patterns in `uploads/player_profile.json`

2. **Scorecard Parsing**: Uses GPT-4o vision to extract structured data from scorecard images, identifying:
   - Course name
   - Tee box names
   - Hole-by-hole par and yardages

3. **Hole Layout Analysis**: 
   - For single hole images: Directly analyzes the hole
   - For full course maps: Locates the specified hole number and focuses analysis on that hole
   - Calculates pixel-to-yard conversion from tee-to-green distance
   - Identifies hazards and calculates yardages from tee

4. **Shot Planning**: Combines:
   - Your player profile (club distances and dispersion)
   - Course information (par, yardage, hazards)
   - Hole layout (hazard positions and yardages)
   
   To generate a strategic plan that maximizes GIR probability while avoiding hazards.

## Notes

- All uploaded data is stored in the `uploads/` directory
- The system supports both single-hole images and full course maps
- When using full course maps, ensure you enter the correct hole number
- Hazard directions can be corrected and recalibrated for improved accuracy
- Tee yardages are automatically populated from parsed scorecard data when available

## Troubleshooting

- **"No module named uvicorn"**: Ensure you've rebuilt the Docker image with `docker compose build --no-cache`
- **Hazard directions incorrect**: Use the recalibration feature to correct directions
- **Wrong hole analyzed**: Double-check the hole number when using full course maps
- **Tee yardage not auto-filling**: Make sure you've parsed the scorecard first (step 2)

