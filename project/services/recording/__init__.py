"""
Services module Enregistrement audio + transcription IA.

Modules exposés :
  * audio_tokens : génération / vérification HMAC pour stream <audio>
  * audio_processing (PR-REC-2) : extraction extraits via pydub/ffmpeg
  * transcription (PR-REC-2) : AssemblyAI SDK wrapper
  * diarization (PR-REC-2) : agrégation segments → speakers + samples
  * speaker_mapping (PR-REC-2) : voix → User mapping + confirmation
  * ai_summary (PR-REC-2) : synthèse compte-rendu via FallbackChain
  * extraction (PR-REC-2) : décisions / actions / risques extraits
"""
