"""
Balance Manager - BigNumber 기반 정확한 잔고 계산
음수 잔고 처리 및 정밀 계산 지원
"""
import logging
from decimal import Decimal, getcontext, ROUND_HALF_UP
from typing import Dict, Optional, Union
from dataclasses import dataclass
from datetime import datetime

# Decimal 정밀도 설정 (암호화폐 거래에 충분한 18자리)
getcontext().prec = 18
getcontext().rounding = ROUND_HALF_UP

logger = logging.getLogger(__name__)


@dataclass
class BalanceInfo:
    """잔고 정보 데이터 클래스"""
    asset: str
    available: Decimal
    locked: Decimal
    total: Decimal
    last_updated: datetime
    
    def __post_init__(self):
        """데이터 검증"""
        if self.total != self.available + self.locked:
            raise ValueError(f"Balance mismatch: total({self.total}) != available({self.available}) + locked({self.locked})")


class NegativeBalanceError(Exception):
    """음수 잔고 에러"""
    def __init__(self, asset: str, current_balance: Decimal, requested_amount: Decimal):
        self.asset = asset
        self.current_balance = current_balance
        self.requested_amount = requested_amount
        super().__init__(
            f"Insufficient balance for {asset}: "
            f"current={current_balance}, requested={requested_amount}, "
            f"shortage={requested_amount - current_balance}"
        )


class BalanceManager:
    """정확한 잔고 계산 및 관리"""
    
    def __init__(self, allow_negative: bool = False):
        """
        Args:
            allow_negative: 음수 잔고 허용 여부 (마진 거래용)
        """
        self.balances: Dict[str, BalanceInfo] = {}
        self.allow_negative = allow_negative
        logger.info(f"BalanceManager initialized (allow_negative={allow_negative})")
    
    def to_decimal(self, value: Union[str, int, float, Decimal]) -> Decimal:
        """안전한 Decimal 변환"""
        if isinstance(value, Decimal):
            return value
        try:
            return Decimal(str(value))
        except Exception as e:
            logger.error(f"Failed to convert {value} to Decimal: {e}")
            raise ValueError(f"Invalid numeric value: {value}")
    
    def set_balance(self, asset: str, available: Union[str, Decimal], locked: Union[str, Decimal] = "0") -> None:
        """잔고 설정"""
        try:
            available_decimal = self.to_decimal(available)
            locked_decimal = self.to_decimal(locked)
            total_decimal = available_decimal + locked_decimal
            
            self.balances[asset] = BalanceInfo(
                asset=asset,
                available=available_decimal,
                locked=locked_decimal,
                total=total_decimal,
                last_updated=datetime.now()
            )
            
            logger.info(f"Balance set for {asset}: available={available_decimal}, locked={locked_decimal}, total={total_decimal}")
            
        except Exception as e:
            logger.error(f"Failed to set balance for {asset}: {e}")
            raise
    
    def get_balance(self, asset: str) -> Optional[BalanceInfo]:
        """잔고 조회"""
        return self.balances.get(asset)
    
    def get_available_balance(self, asset: str) -> Decimal:
        """사용 가능 잔고 조회"""
        balance_info = self.get_balance(asset)
        if balance_info is None:
            return Decimal("0")
        return balance_info.available
    
    def check_sufficient_balance(self, asset: str, amount: Union[str, Decimal]) -> bool:
        """잔고 충분성 검사"""
        amount_decimal = self.to_decimal(amount)
        available = self.get_available_balance(asset)
        
        if self.allow_negative:
            return True  # 음수 허용 시 항상 충분
        
        return available >= amount_decimal
    
    def reserve_balance(self, asset: str, amount: Union[str, Decimal]) -> bool:
        """잔고 예약 (available → locked)"""
        try:
            amount_decimal = self.to_decimal(amount)
            
            if not self.check_sufficient_balance(asset, amount_decimal):
                if not self.allow_negative:
                    current_balance = self.get_available_balance(asset)
                    raise NegativeBalanceError(asset, current_balance, amount_decimal)
            
            balance_info = self.get_balance(asset)
            if balance_info is None:
                # 잔고가 없으면 0으로 초기화
                self.set_balance(asset, "0", "0")
                balance_info = self.get_balance(asset)
            
            new_available = balance_info.available - amount_decimal
            new_locked = balance_info.locked + amount_decimal
            
            self.set_balance(asset, new_available, new_locked)
            
            logger.info(f"Reserved {amount_decimal} {asset}: available={new_available}, locked={new_locked}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to reserve {amount} {asset}: {e}")
            raise
    
    def release_balance(self, asset: str, amount: Union[str, Decimal]) -> bool:
        """잔고 해제 (locked → available)"""
        try:
            amount_decimal = self.to_decimal(amount)
            
            balance_info = self.get_balance(asset)
            if balance_info is None:
                logger.warning(f"No balance info for {asset}, cannot release {amount_decimal}")
                return False
            
            if balance_info.locked < amount_decimal:
                logger.error(f"Insufficient locked balance for {asset}: locked={balance_info.locked}, requested={amount_decimal}")
                return False
            
            new_available = balance_info.available + amount_decimal
            new_locked = balance_info.locked - amount_decimal
            
            self.set_balance(asset, new_available, new_locked)
            
            logger.info(f"Released {amount_decimal} {asset}: available={new_available}, locked={new_locked}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to release {amount} {asset}: {e}")
            raise
    
    def deduct_balance(self, asset: str, amount: Union[str, Decimal]) -> bool:
        """잔고 차감 (locked에서 실제 차감)"""
        try:
            amount_decimal = self.to_decimal(amount)
            
            balance_info = self.get_balance(asset)
            if balance_info is None:
                logger.warning(f"No balance info for {asset}, cannot deduct {amount_decimal}")
                return False
            
            if balance_info.locked < amount_decimal:
                logger.error(f"Insufficient locked balance for {asset}: locked={balance_info.locked}, requested={amount_decimal}")
                return False
            
            new_locked = balance_info.locked - amount_decimal
            
            self.set_balance(asset, balance_info.available, new_locked)
            
            logger.info(f"Deducted {amount_decimal} {asset}: available={balance_info.available}, locked={new_locked}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to deduct {amount} {asset}: {e}")
            raise
    
    def add_balance(self, asset: str, amount: Union[str, Decimal]) -> bool:
        """잔고 추가 (available에 추가)"""
        try:
            amount_decimal = self.to_decimal(amount)
            
            balance_info = self.get_balance(asset)
            if balance_info is None:
                self.set_balance(asset, amount_decimal, "0")
            else:
                new_available = balance_info.available + amount_decimal
                self.set_balance(asset, new_available, balance_info.locked)
            
            logger.info(f"Added {amount_decimal} {asset}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to add {amount} {asset}: {e}")
            raise
    
    def get_all_balances(self) -> Dict[str, BalanceInfo]:
        """모든 잔고 조회"""
        return self.balances.copy()
    
    def calculate_portfolio_value(self, prices: Dict[str, Union[str, Decimal]]) -> Decimal:
        """포트폴리오 총 가치 계산"""
        total_value = Decimal("0")
        
        for asset, balance_info in self.balances.items():
            if asset in prices:
                price = self.to_decimal(prices[asset])
                asset_value = balance_info.total * price
                total_value += asset_value
                logger.debug(f"{asset}: {balance_info.total} * {price} = {asset_value}")
        
        logger.info(f"Portfolio total value: {total_value}")
        return total_value


# 단위 테스트
if __name__ == "__main__":
    import unittest
    
    class TestBalanceManager(unittest.TestCase):
        
        def setUp(self):
            self.balance_manager = BalanceManager(allow_negative=False)
            self.balance_manager_negative = BalanceManager(allow_negative=True)
        
        def test_decimal_conversion(self):
            """Decimal 변환 테스트"""
            bm = self.balance_manager
            
            # 정상 케이스
            self.assertEqual(bm.to_decimal("100.5"), Decimal("100.5"))
            self.assertEqual(bm.to_decimal(100), Decimal("100"))
            self.assertEqual(bm.to_decimal(100.5), Decimal("100.5"))
            self.assertEqual(bm.to_decimal(Decimal("100.5")), Decimal("100.5"))
            
            # 에러 케이스
            with self.assertRaises(ValueError):
                bm.to_decimal("invalid")
        
        def test_set_get_balance(self):
            """잔고 설정/조회 테스트"""
            bm = self.balance_manager
            
            bm.set_balance("BTC", "1.5", "0.5")
            balance = bm.get_balance("BTC")
            
            self.assertIsNotNone(balance)
            self.assertEqual(balance.available, Decimal("1.5"))
            self.assertEqual(balance.locked, Decimal("0.5"))
            self.assertEqual(balance.total, Decimal("2.0"))
        
        def test_sufficient_balance_check(self):
            """잔고 충분성 검사 테스트"""
            bm = self.balance_manager
            bm.set_balance("BTC", "1.0", "0")
            
            # 충분한 경우
            self.assertTrue(bm.check_sufficient_balance("BTC", "0.5"))
            self.assertTrue(bm.check_sufficient_balance("BTC", "1.0"))
            
            # 부족한 경우
            self.assertFalse(bm.check_sufficient_balance("BTC", "1.5"))
        
        def test_negative_balance_error(self):
            """음수 잔고 에러 테스트"""
            bm = self.balance_manager
            bm.set_balance("BTC", "1.0", "0")
            
            # 음수 허용 안함 - 에러 발생
            with self.assertRaises(NegativeBalanceError) as context:
                bm.reserve_balance("BTC", "1.5")
            
            error = context.exception
            self.assertEqual(error.asset, "BTC")
            self.assertEqual(error.current_balance, Decimal("1.0"))
            self.assertEqual(error.requested_amount, Decimal("1.5"))
        
        def test_negative_balance_allowed(self):
            """음수 잔고 허용 테스트"""
            bm = self.balance_manager_negative
            bm.set_balance("BTC", "1.0", "0")
            
            # 음수 허용 - 정상 처리
            result = bm.reserve_balance("BTC", "1.5")
            self.assertTrue(result)
            
            balance = bm.get_balance("BTC")
            self.assertEqual(balance.available, Decimal("-0.5"))
            self.assertEqual(balance.locked, Decimal("1.5"))
        
        def test_reserve_release_balance(self):
            """잔고 예약/해제 테스트"""
            bm = self.balance_manager
            bm.set_balance("BTC", "2.0", "0")
            
            # 예약
            bm.reserve_balance("BTC", "1.0")
            balance = bm.get_balance("BTC")
            self.assertEqual(balance.available, Decimal("1.0"))
            self.assertEqual(balance.locked, Decimal("1.0"))
            
            # 해제
            bm.release_balance("BTC", "0.5")
            balance = bm.get_balance("BTC")
            self.assertEqual(balance.available, Decimal("1.5"))
            self.assertEqual(balance.locked, Decimal("0.5"))
        
        def test_deduct_add_balance(self):
            """잔고 차감/추가 테스트"""
            bm = self.balance_manager
            bm.set_balance("BTC", "1.0", "1.0")
            
            # 차감
            bm.deduct_balance("BTC", "0.5")
            balance = bm.get_balance("BTC")
            self.assertEqual(balance.available, Decimal("1.0"))
            self.assertEqual(balance.locked, Decimal("0.5"))
            
            # 추가
            bm.add_balance("BTC", "0.5")
            balance = bm.get_balance("BTC")
            self.assertEqual(balance.available, Decimal("1.5"))
            self.assertEqual(balance.locked, Decimal("0.5"))
        
        def test_portfolio_value_calculation(self):
            """포트폴리오 가치 계산 테스트"""
            bm = self.balance_manager
            bm.set_balance("BTC", "1.0", "0.5")  # total: 1.5
            bm.set_balance("ETH", "10.0", "5.0")  # total: 15.0
            
            prices = {
                "BTC": "50000",
                "ETH": "3000"
            }
            
            # BTC: 1.5 * 50000 = 75000
            # ETH: 15.0 * 3000 = 45000
            # Total: 120000
            total_value = bm.calculate_portfolio_value(prices)
            self.assertEqual(total_value, Decimal("120000"))
    
    # 테스트 실행
    unittest.main()