class CombinationEngine:
    def __init__(self, gamma_g: float = 1.35, gamma_q: float = 1.50, psi0: float = 0.7, psi1: float = 0.5, psi2: float = 0.3):
        self.gamma_g = gamma_g
        self.gamma_q = gamma_q
        self.psi0 = psi0
        self.psi1 = psi1
        self.psi2 = psi2

    def uls_fundamental(self, gk: float, qk: float) -> float:
        return self.gamma_g * gk + self.gamma_q * qk

    def sls_rare(self, gk: float, qk: float) -> float:
        return gk + qk

    def sls_frequent(self, gk: float, qk: float) -> float:
        return gk + self.psi1 * qk

    def sls_quasi_permanent(self, gk: float, qk: float) -> float:
        return gk + self.psi2 * qk
