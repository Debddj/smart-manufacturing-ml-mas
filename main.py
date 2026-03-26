"""
Entry point — smart-manufacturing-ml-mas

Phase flags:
    USE_DQN             = False  → original tabular Q-learning (safe, no new deps)
    USE_MULTI_WAREHOUSE = False  → original single warehouse

    USE_DQN             = True   → PyTorch DQN (requires: pip install torch)
    USE_MULTI_WAREHOUSE = True   → 3-warehouse network with Branch A/B/C logic

Run original system (no changes):
    python main.py

Run upscaled DQN system:
    Set USE_DQN = True and USE_MULTI_WAREHOUSE = True below, then:
    pip install torch
    python main.py
"""

from data_processing.preprocess_pipeline import DataPreprocessor
from forecasting.demand_forecasting       import DemandForecaster
from simulation.simulation_runner         import train_rl_agent

# ── Phase flags ────────────────────────────────────────────────────────────────
USE_DQN             = False   # ← Set True for upscaled DQN system
USE_MULTI_WAREHOUSE = False   # ← Set True together with USE_DQN
REWARD_PROFILE      = "balanced"  # balanced | speed | cost | resilience
EPISODES            = 100

def main():
    print("Preprocessing...")
    pipeline = DataPreprocessor("data/raw/demand.csv")
    X_train, X_test, y_train, y_test = pipeline.run()

    print("Training ML model...")
    model = DemandForecaster()
    model.train(X_train, y_train)
    predictions = model.predict(X_test)

    if USE_DQN:
        print(f"\nUpscaled mode: DQN + {'multi-warehouse' if USE_MULTI_WAREHOUSE else 'single-warehouse'}")
        print(f"Reward profile: {REWARD_PROFILE}")
        print("Ensure PyTorch is installed: pip install torch\n")

    print(f"Training RL agent ({EPISODES} episodes)...")
    train_rl_agent(
        predictions,
        episodes            = EPISODES,
        use_dqn             = USE_DQN,
        use_multi_warehouse = USE_MULTI_WAREHOUSE,
        reward_profile      = REWARD_PROFILE,
    )

if __name__ == "__main__":
    main() 