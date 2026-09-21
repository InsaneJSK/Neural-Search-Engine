"""Download the prepared Kaggle training dataset (not needed for search)."""

import kagglehub


def main():
    path = kagglehub.dataset_download("insanejsk/nse-dr")
    print("Path to dataset files:", path)


if __name__ == "__main__":
    main()
