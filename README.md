# Twinkle Twinkle - Kids Education Platform

A magical kids' education platform featuring AI-powered story and comic generation.

## Backend (Django DRF)

### Setup
```bash
cd ~/PycharmProjects/Twinkle_Twinkle
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### Environment Setup
```bash
cp .env.example .env
# Edit .env with your settings
```

### Database Setup
```bash
python manage.py makemigrations
python manage.py migrate
python manage.py createsuperuser
```

### Run Server
```bash
python manage.py runserver
```

## API Endpoints

### Stories
- `GET /api/v1/stories/` - List all stories
- `GET /api/v1/stories/{id}/` - Get story details
- `POST /api/v1/stories/generate/` - Generate new story
- `POST /api/v1/stories/{id}/like/` - Like/unlike story

### Comics
- `GET /api/v1/comics/` - List all comics
- `GET /api/v1/comics/{id}/` - Get comic details
- `POST /api/v1/comics/generate/` - Generate new comic
- `POST /api/v1/comics/{id}/like/` - Like/unlike comic

### Users
- `GET /api/v1/users/profile/` - Get user profile
- `PUT /api/v1/users/profile/` - Update user profile
- `GET/POST /api/v1/users/progress/` - Reading progress
- `GET /api/v1/users/stats/` - User statistics

## Features

### Stories
- AI-powered story generation using OpenAI GPT
- Age-appropriate content (3-5, 6-8, 9-12 years)
- Difficulty levels (easy, medium, hard)
- Character management
- Moral lessons integration
- Like/favorite system

### Comics
- AI-generated comic panels and images
- Multiple art styles (cartoon, anime, realistic, watercolor)
- Visual storytelling
- Character avatars
- Panel-by-panel reading experience

### User Features
- Profile management with age groups
- Reading progress tracking
- Favorite themes
- Personal statistics

## Technologies Used

- **Backend**: Django 4.2, Django REST Framework
- **Database**: SQLite (development), PostgreSQL (production ready)
- **AI Integration**: OpenAI GPT for text, DALL-E for images
- **Background Tasks**: Celery with Redis
- **Image Processing**: Pillow

## Configuration

### Environment Variables
- `DEBUG`: Development mode flag
- `SECRET_KEY`: Django secret key
- `OPENAI_API_KEY`: OpenAI API key for AI generation

### CORS Settings
Configured for frontend at `http://localhost:5173` (Vite default)

## Development Notes

- All AI generation is handled through service classes
- Models include proper validation and constraints
- Admin interface available for content management
- Responsive design considerations built-in