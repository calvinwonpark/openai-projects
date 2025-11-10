# AI/ML Product Deployment Patterns

## ML System Architecture

### Training vs. Inference
- **Training** - Build model from data (offline, batch)
- **Inference** - Use model to make predictions (online, real-time)
- **Different requirements** - Training needs compute, inference needs latency

### Model Serving Patterns

**Batch Inference**
- **Process in batches** - Run predictions on dataset
- **When**: Not time-sensitive, large volumes
- **Example**: Daily user recommendations, email personalization
- **Infrastructure**: Scheduled jobs, batch processing

**Real-Time Inference**
- **On-demand predictions** - API endpoint, low latency
- **When**: User-facing features, immediate feedback
- **Example**: Fraud detection, search ranking, chatbots
- **Infrastructure**: API servers, model endpoints

**Edge Inference**
- **Run on device** - Mobile app, browser
- **When**: Privacy-sensitive, offline capability
- **Example**: Image filters, voice assistants
- **Challenge**: Model size, device compute limits

## Model Deployment Strategies

### Shadow Mode
- **Run new model alongside old** - Don't affect users
- **Compare outputs** - Validate new model performance
- **When**: Testing new model before full rollout
- **Benefit**: Low risk, real-world validation

### Canary Deployment
- **Gradual rollout** - 5% → 25% → 100% of traffic
- **Monitor metrics** - Rollback if performance degrades
- **When**: New model version
- **Benefit**: Catch issues early, minimize impact

### A/B Testing
- **Split traffic** - 50% old model, 50% new model
- **Compare outcomes** - Which performs better?
- **When**: Testing model improvements
- **Metrics**: Accuracy, business metrics (conversion, revenue)

## Model Monitoring

### Data Drift
- **Input distribution changes** - Model trained on old data
- **Detection**: Monitor feature distributions
- **Impact**: Model performance degrades
- **Solution**: Retrain on new data

### Concept Drift
- **Target relationship changes** - What predicts Y changes
- **Detection**: Monitor prediction accuracy
- **Impact**: Model becomes less accurate
- **Solution**: Retrain with recent data

### Model Performance Metrics
- **Accuracy** - Overall correctness
- **Precision/Recall** - For classification tasks
- **AUC-ROC** - For binary classification
- **Business metrics** - Revenue, conversion, engagement

## Feature Engineering & Storage

### Feature Stores
- **Centralized features** - Reusable across models
- **Consistency** - Same features for training and inference
- **Tools**: Feast, Tecton, AWS SageMaker Feature Store
- **Benefit**: Faster model development, consistency

### Online vs. Offline Features
- **Offline features** - Computed in batch (user history, aggregates)
- **Online features** - Computed in real-time (current session, time)
- **Challenge**: Keep online/offline features consistent
- **Solution**: Feature store with both modes

## Model Versioning

### Model Registry
- **Track versions** - Which model is in production?
- **Metadata** - Training data, hyperparameters, metrics
- **Rollback capability** - Revert to previous version
- **Tools**: MLflow, Weights & Biases, DVC

### Model Artifacts
- **Store models** - Serialized model files
- **Version control** - Git LFS, S3, model registry
- **Reproducibility** - Same code + data = same model
- **Documentation** - Model card with performance, limitations

## LLM-Specific Patterns

### Prompt Engineering
- **Design prompts** - Clear instructions, examples
- **Few-shot learning** - Include examples in prompt
- **Chain-of-thought** - Break complex tasks into steps
- **Iterate** - Test different prompt variations

### RAG (Retrieval-Augmented Generation)
- **Retrieve relevant context** - From knowledge base
- **Augment prompt** - Include retrieved context
- **Generate answer** - LLM uses context to answer
- **Benefit**: Grounded responses, up-to-date information

### Fine-Tuning vs. Prompting
- **Prompting** - Use pre-trained model as-is
- **Fine-tuning** - Train on your specific data
- **When to fine-tune**: Need domain-specific behavior
- **Trade-off**: Cost and complexity vs. performance

## Infrastructure Patterns

### Serverless ML
- **AWS Lambda** - For small models, low latency
- **Google Cloud Functions** - Serverless inference
- **Azure Functions** - Pay per request
- **Benefit**: No server management, auto-scaling

### Containerized Models
- **Docker containers** - Package model + dependencies
- **Kubernetes** - Orchestrate model deployments
- **Auto-scaling** - Scale based on traffic
- **Benefit**: Consistent environment, easy deployment

### Model Endpoints
- **Dedicated API** - REST or gRPC endpoint
- **Load balancing** - Distribute inference requests
- **Caching** - Cache common predictions
- **Tools**: TensorFlow Serving, TorchServe, SageMaker

## Cost Optimization

### Model Optimization
- **Quantization** - Reduce precision (float32 → int8)
- **Pruning** - Remove unnecessary parameters
- **Distillation** - Train smaller model from large one
- **Benefit**: Faster inference, lower cost

### Caching Predictions
- **Cache common queries** - Same input = same output
- **TTL-based** - Expire after time period
- **When**: Deterministic models, expensive inference
- **Trade-off**: Stale predictions vs. cost savings

### Batch Processing
- **Process in batches** - More efficient than one-by-one
- **When**: Not time-sensitive
- **Benefit**: Better GPU utilization, lower cost per prediction

## Best Practices

1. **Start simple** - Rule-based → simple ML → complex ML
2. **Measure everything** - Model performance, latency, cost
3. **Monitor in production** - Data drift, performance degradation
4. **Version control** - Models, code, data
5. **Automate retraining** - Schedule regular model updates
6. **Test thoroughly** - Unit tests, integration tests, A/B tests
7. **Document** - Model cards, API docs, runbooks
8. **Plan for failure** - Fallback models, graceful degradation

## Common Mistakes

1. **No monitoring** - Deploy and forget
2. **Training-serving skew** - Different features in training vs. inference
3. **Ignoring latency** - Model too slow for real-time use
4. **No fallback** - System breaks if model fails
5. **Over-engineering** - Complex system when simple works
6. **No versioning** - Can't rollback or reproduce
7. **Ignoring costs** - Expensive infrastructure for simple use case

