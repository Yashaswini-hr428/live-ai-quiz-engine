# Live AI Quiz Engine

A real-time AI-powered quiz platform built with Python.

## Features

- AI-generated multiple-choice questions using the Anthropic API
- Real-time multiplayer quiz rooms
- Live scoring and leaderboard
- Speed and streak bonuses
- Custom questions created by the host
- Offline question-bank fallback
- Open Trivia DB fallback for general trivia
- Browser-based interface
- WebSocket communication for real-time updates
- Optional public internet access using a tunnel

## Technologies Used

- Python
- Asyncio
- WebSockets
- HTML
- CSS
- JavaScript
- Anthropic API
- Open Trivia DB API

## How It Works

1. The host creates a quiz room and selects a topic.
2. Questions can be generated using AI or selected from fallback question sources.
3. Players join the room using a room code.
4. Questions are displayed simultaneously to all players.
5. Players receive points based on correctness and response speed.
6. The leaderboard updates in real time.
7. Final scores are displayed at the end of the quiz.

## Running the Project

Make sure Python 3 is installed.

```bash
python quiz_engine.py
