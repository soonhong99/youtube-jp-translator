#!/bin/bash

echo "🚀 Creating streaming-specific Kafka topics..."

# 스트리밍 STT 토픽
echo "📝 Creating stt_chunks topic..."
kafka-topics --create --if-not-exists --topic stt_chunks --bootstrap-server kafka:9092 --partitions 5 --replication-factor 1

# 번역 작업 큐
echo "🔄 Creating translation_queue topic..."
kafka-topics --create --if-not-exists --topic translation_queue --bootstrap-server kafka:9092 --partitions 8 --replication-factor 1

# 실시간 결과 스트림
echo "⚡ Creating realtime_results topic..."
kafka-topics --create --if-not-exists --topic realtime_results --bootstrap-server kafka:9092 --partitions 3 --replication-factor 1

# 모니터링 메트릭
echo "📊 Creating performance_metrics topic..."
kafka-topics --create --if-not-exists --topic performance_metrics --bootstrap-server kafka:9092 --partitions 2 --replication-factor 1

# 스트리밍 제어 명령
echo "🎮 Creating streaming_control topic..."
kafka-topics --create --if-not-exists --topic streaming_control --bootstrap-server kafka:9092 --partitions 1 --replication-factor 1

echo "✅ Streaming topics created successfully!"

echo "📋 Current topic list:"
kafka-topics --list --bootstrap-server kafka:9092

echo "🔍 Topic details:"
for topic in stt_chunks translation_queue realtime_results performance_metrics streaming_control; do
    echo "--- Topic: $topic ---"
    kafka-topics --describe --topic $topic --bootstrap-server kafka:9092
done

echo "🎉 Setup complete!"