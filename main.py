from data_processing.preprocess_pipeline import DataPreprocessor
from forecasting.demand_forecasting import DemandForecaster
from simulation.simulation_runner import train_rl_agent

def main():

    print("Preprocessing...")
    pipeline = DataPreprocessor("data/raw/demand.csv")
    X_train, X_test, y_train, y_test = pipeline.run()

    print("Training ML model...")
    model = DemandForecaster()
    model.train(X_train, y_train)

    predictions = model.predict(X_test)

    print("Training RL agent...")
    train_rl_agent(predictions, episodes=100)

if __name__ == "__main__":
    main() 