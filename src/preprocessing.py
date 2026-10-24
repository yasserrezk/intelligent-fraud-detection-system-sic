import numpy as np
import pandas as pd
from sklearn.base import BaseEstimator, TransformerMixin
from sklearn.preprocessing import OrdinalEncoder
from sklearn.utils.validation import check_is_fitted


def _check_columns(X: pd.DataFrame, columns) -> None:
    missing = set(columns) - set(X.columns)
    if missing:
        raise KeyError(f"Missing columns: {sorted(missing)}")


class DataCleaner(BaseEstimator, TransformerMixin):
    """Drop null-heavy columns (learned in fit), duplicate rows, and null rows.

    Column drops are safe in a Pipeline. Row drops (drop_duplicates,
    drop_null_rows) change the row count and desync X from y, so only use
    them outside a Pipeline, on train data, before splitting off y.
    """

    def __init__(
        self,
        drop_duplicates: bool = True,
        null_threshold: float | None = 0.5,
        drop_null_rows: bool = False,
    ):
        self.drop_duplicates = drop_duplicates
        self.null_threshold = null_threshold
        self.drop_null_rows = drop_null_rows

    def fit(self, X: pd.DataFrame, y=None):
        if self.null_threshold is not None and not 0 <= self.null_threshold <= 1:
            raise ValueError("null_threshold must be in [0, 1] or None.")

        if self.null_threshold is None:
            self.columns_to_drop_ = np.array([], dtype=object)
        else:
            null_ratio = X.isna().mean()
            self.columns_to_drop_ = np.asarray(
                null_ratio[null_ratio > self.null_threshold].index, dtype=object
            )
        self.feature_names_in_ = np.asarray(X.columns, dtype=object)
        return self

    def transform(self, X: pd.DataFrame) -> pd.DataFrame:
        check_is_fitted(self, "columns_to_drop_")

        X = X.drop(columns=self.columns_to_drop_, errors="ignore")
        if self.drop_duplicates:
            X = X.drop_duplicates()
        if self.drop_null_rows:
            X = X.dropna()
        return X.copy()

    def get_feature_names_out(self, input_features=None):
        check_is_fitted(self, "columns_to_drop_")
        return np.array(
            [c for c in self.feature_names_in_ if c not in set(self.columns_to_drop_)],
            dtype=object,
        )


class TimeDeltaFeatures(BaseEstimator, TransformerMixin):
    """Derive day_index, elapsed_hour, elapsed_day_of_week from a seconds timedelta."""

    def __init__(self, column: str = "TransactionDT", drop_original: bool = True):
        self.column = column
        self.drop_original = drop_original

    def fit(self, X: pd.DataFrame, y=None):
        _check_columns(X, [self.column])
        self.feature_names_in_ = np.asarray(X.columns, dtype=object)
        return self

    def transform(self, X: pd.DataFrame) -> pd.DataFrame:
        check_is_fitted(self, "feature_names_in_")
        _check_columns(X, [self.column])

        X = X.copy()
        seconds = X[self.column]
        X["day_index"] = seconds // 86_400
        X["elapsed_hour"] = (seconds // 3_600) % 24
        X["elapsed_day_of_week"] = X["day_index"] % 7
        if self.drop_original:
            X = X.drop(columns=[self.column])
        return X

    def get_feature_names_out(self, input_features=None):
        check_is_fitted(self, "feature_names_in_")
        names = [c for c in self.feature_names_in_ if not (self.drop_original and c == self.column)]
        return np.array(
            [*names, "day_index", "elapsed_hour", "elapsed_day_of_week"],
            dtype=object,
        )


class Log1pTransformer(BaseEstimator, TransformerMixin):
    """Apply np.log1p to the selected numeric columns."""

    def __init__(self, columns: list[str]):
        self.columns = columns

    def _validate(self, X: pd.DataFrame) -> None:
        _check_columns(X, self.columns)
        numeric = X[self.columns].select_dtypes(include="number").columns
        if not numeric.equals(pd.Index(self.columns)):
            raise TypeError("All selected columns must be numeric.")
        if (X[self.columns].dropna() <= -1).any().any():
            raise ValueError("np.log1p requires values greater than -1.")

    def fit(self, X: pd.DataFrame, y=None):
        self._validate(X)
        self.feature_names_in_ = np.asarray(X.columns, dtype=object)
        return self

    def transform(self, X: pd.DataFrame) -> pd.DataFrame:
        check_is_fitted(self, "feature_names_in_")
        self._validate(X)

        X = X.copy()
        X[self.columns] = np.log1p(X[self.columns])
        return X

    def get_feature_names_out(self, input_features=None):
        check_is_fitted(self, "feature_names_in_")
        return self.feature_names_in_


class CategoryEncoder(BaseEstimator, TransformerMixin):
    """OrdinalEncoder on selected columns; unseen -> -1, NaN stays NaN."""

    def __init__(self, columns: list[str]):
        self.columns = columns

    def fit(self, X: pd.DataFrame, y=None):
        _check_columns(X, self.columns)
        self.encoder_ = OrdinalEncoder(
            handle_unknown="use_encoded_value",
            unknown_value=-1,
            encoded_missing_value=np.nan,
        ).fit(X[self.columns])
        self.feature_names_in_ = np.asarray(X.columns, dtype=object)
        return self

    def transform(self, X: pd.DataFrame) -> pd.DataFrame:
        check_is_fitted(self, "encoder_")
        _check_columns(X, self.columns)

        X = X.copy()
        X[self.columns] = self.encoder_.transform(X[self.columns])
        return X

    def get_feature_names_out(self, input_features=None):
        check_is_fitted(self, "feature_names_in_")
        return self.feature_names_in_


