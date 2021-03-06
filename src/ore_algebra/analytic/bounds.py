# -*- coding: utf-8 - vim: tw=79
r"""
Error bounds
"""

from __future__ import print_function

import itertools, logging, warnings

from sage.arith.srange import srange
from sage.misc.cachefunc import cached_function, cached_method
from sage.misc.lazy_string import lazy_string
from sage.misc.misc_c import prod
from sage.misc.random_testing import random_testing
from sage.rings.all import CIF
from sage.rings.complex_arb import CBF, ComplexBallField
from sage.rings.infinity import infinity
from sage.rings.integer import Integer
from sage.rings.integer_ring import ZZ
from sage.rings.polynomial.polynomial_element import Polynomial
from sage.rings.polynomial.polynomial_ring import polygen
from sage.rings.polynomial.polynomial_ring_constructor import PolynomialRing
from sage.rings.power_series_ring import PowerSeriesRing
from sage.rings.qqbar import QQbar
from sage.rings.rational_field import QQ
from sage.rings.real_arb import RBF
from sage.rings.real_mpfi import RIF
from sage.rings.real_mpfr import RealField, RR
from sage.structure.factorization import Factorization

from .. import ore_algebra
from . import local_solutions, utilities

from .safe_cmp import *
from .shiftless import squarefree_part

logger = logging.getLogger(__name__)

IR, IC = RBF, CBF # TBI

class BoundPrecisionError(Exception):
    pass

######################################################################
# Majorant series
######################################################################

class MajorantSeries(object):
    r"""
    A formal power series with nonnegative coefficients
    """

    def __init__(self, variable_name, cvrad=IR.zero()):
        self.variable_name = variable_name
        self.cvrad = IR(cvrad)
        assert self.cvrad >= IR.zero()

    def bound_series(self, rad, ord):
        r"""
        Compute a termwise bound on the series expansion of self at rad to
        order O(x^ord).

        More precisely, the upper bound of each interval coefficient is a bound
        on the corresponding coefficient of self (which itself is a bound on
        the absolute value of the corresponding coefficient of the series this
        object is intended to bound).
        """
        return self.series(rad, ord)

    def series(self, rad, ord):
        r"""
        Compute the series expansion of self at rad to order O(x^ord).

        With rad = 0, this returns the majorant series itself. More generally,
        this can be used to obtain bounds on the derivatives of the series this
        majorant bounds on disks contained within its disk of convergence.
        """
        raise NotImplementedError

    def __call__(self, rad):
        r"""
        Bound the value of this series at rad ≥ 0.
        """
        return self.series(rad, 1)[0]

    def bound(self, rad, derivatives=1):
        """
        Bound the Frobenius norm of the vector

            [g(rad), g'(rad), g''(rad)/2, ..., 1/(d-1)!·g^(d-1)(rad)]

        where d = ``derivatives`` and g is this majorant series. The result is
        a bound for

            [f(z), f'(z), f''(z)/2, ..., 1/(d-1)!·f^(d-1)(z)]

        for all z with |z| ≤ rad.
        """
        if not safe_le(rad, self.cvrad): # intervals!
            return IR(infinity)
        else:
            ser = self.bound_series(rad, derivatives)
            sqnorm = sum((c.abs()**2 for c in ser), IR.zero())
            return sqnorm.sqrtpos()

    def _test(self, fun=0, prec=50, return_difference=False):
        r"""
        Check that ``self`` is *plausibly* a majorant of ``fun``.

        This function in intended for debugging purposes. It does *not* perform
        a rigorous check that ``self`` is a majorant series of ``fun``, and may
        yield false positives (but no false negatives).

        The reference function ``fun`` should be convertible to a series with
        complex ball coefficients. If ``fun`` is omitted, check that ``self``
        has nonnegative coefficients.

        TESTS::

            sage: from ore_algebra.analytic.bounds import *
            sage: Pol.<z> = RBF[]
            sage: maj = RationalMajorant([(Pol(1), Factorization([(1-z,1)]))])
            sage: maj._test(11/10*z^30)
            Traceback (most recent call last):
            ...
            AssertionError: (30, [-0.10000000000000 +/- 8.00e-16], '< 0')
        """
        Series = PowerSeriesRing(IR, self.variable_name, prec)
        # CIF to work around problem with sage power series, should be IC
        ComplexSeries = PowerSeriesRing(CIF, self.variable_name, prec)
        maj = Series(self.bound_series(0, prec))
        ref = Series([iv.abs() for iv in ComplexSeries(fun)], prec=prec)
        delta = (maj - ref).padded_list()
        if len(delta) < prec:
            warnings.warn("checking {} term(s) instead of {} (cancellation"
                    " during series expansion?)".format(len(delta), prec))
        for i, c in enumerate(delta):
            # the lower endpoint of a coefficient of maj is not a bound in
            # general, and the series expansion can overestimate the
            # coefficients of ref
            if c < IR.zero():
                raise AssertionError(i, c, '< 0')
        if return_difference:
            return delta

def _zero_free_rad(pols):
    r"""
    Return the radius of a disk around the origin without zeros of any of the
    polynomials in pols.
    """
    if all(pol.degree() == 0 for pol in pols):
        return IR(infinity)
    if all(pol.degree() == 1 and pol.leading_coefficient().abs().is_one()
            for pol in pols):
        rad = IR(infinity).min(*(IR(pol[0].abs()) for pol in pols))
        rad = IR(rad.lower())
        assert rad >= IR.zero()
        return rad
    raise NotImplementedError

class RationalMajorant(MajorantSeries):
    r"""
    A rational power series with nonnegative coefficients, represented as an
    unevaluated sum of rational fractions with factored denominators.

    TESTS::

        sage: from ore_algebra.analytic.bounds import *
        sage: Pol.<z> = RBF[]
        sage: den = Factorization([(1-z, 2), (2-z, 1)])
        sage: one = Pol.one().factor()
        sage: maj = RationalMajorant([(1 + z, one), (z^2, den)]) ; maj
        1.000... + 1.000...*z + z^2/((-z + 2.000...) * (-z + 1.000...)^2)
        sage: maj(1/2)
        [2.166...]
        sage: maj*(z^10)
        1.000...*z^10 + 1.000...*z^11 + z^12/((-z + 2.000...) * (-z + 1.000...)^2)
        sage: maj.cvrad
        1.000000000000000
        sage: maj.series(0, 4)
        1.250000000000000*z^3 + 0.5000000000000000*z^2 + z + 1.000000000000000
        sage: maj._test()
        sage: maj._test(1 + z + z^2/((1-z)^2*(2-z)), return_difference=True)
        [0, 0, 0, ...]
        sage: maj._test(1 + z + z^2/((1-z)*(2-z)), return_difference=True)
        [0, 0, 0, 0.5000000000000000, 1.250000000000000, ...]
    """

    def __init__(self, fracs):
        self.Poly = Poly = fracs[0][0].parent().change_ring(IR)
        self._Poly_IC = fracs[0][0].parent().change_ring(IC)
        cvrad = _zero_free_rad([-fac for _, den in fracs for fac, _ in den
                                     if fac.degree() > 0])
        super(self.__class__, self).__init__(Poly.variable_name(), cvrad=cvrad)
        self.fracs = []
        for num, den in fracs:
            if isinstance(num, Polynomial) and isinstance(den, Factorization):
                if not den.unit().is_one():
                    raise ValueError("expected a denominator with unit part 1")
                assert den.universe() is Poly or list(den) == []
                self.fracs.append((num, den))
            else:
                raise TypeError

    def __repr__(self):
        res = ""
        Series = self.Poly.completion(self.Poly.gen())
        def term(num, den):
            if den.value() == 1:
                return repr(Series(num))
            elif num.is_term():
                return "{}/({})".format(num, den)
            else:
                return "({})/({})".format(num._coeff_repr(), den)
        res = " + ".join(term(num, den) for num, den in self.fracs if num)
        return res if res != "" else "0"

    def series(self, rad, ord):
        Pol = self._Poly_IC # XXX: switch to self.Poly once arb_polys are interfaced
        pert_rad = Pol([rad, 1])
        res = Pol.zero()
        for num, den in self.fracs:
            den_ser = Pol.one()
            for lin, mult in den:
                fac_ser = lin(pert_rad).power_trunc(mult, ord)
                den_ser = den_ser._mul_trunc_(fac_ser, ord)
            # slow; hopefully the fast Taylor shift will help...
            num_ser = Pol(num).compose_trunc(pert_rad, ord)
            res += num_ser._mul_trunc_(den_ser.inverse_series_trunc(ord), ord)
        return res

    def bound_integral(self, rad, ord):
        r"""
        Compute a termwise bound on the series expansion of int(self, 0..z) at
        z = rad, to order O(z^ord).
        """
        # For each summand f = num/den of self, we bound the series int(f,0..z)
        # by int(num,0..z)/den(z), using the fact that num and 1/den have
        # nonnegative coefficients and the bound int(fg) << int(f)·g (which
        # can be proved by integrating by parts). We then compose with rad+ε to
        # get the desired series expansion.
        # (Alternative algorithm: only bound the constant term this way,
        # use self.series().integral() for the remaining terms. Probably
        # slightly tighter and costlier.)
        Pol = self._Poly_IC # XXX: switch to self.Poly
        pert_rad = Pol([rad, 1])
        res = Pol.zero()
        for num, den in self.fracs:
            den_ser = Pol.one()
            for lin, mult in den:
                fac_ser = lin(pert_rad).power_trunc(mult, ord)
                den_ser = den_ser._mul_trunc_(fac_ser, ord)
            num_ser = Pol(num.integral()).compose_trunc(pert_rad, ord)
            res += num_ser._mul_trunc_(den_ser.inverse_series_trunc(ord), ord)
            logger.debug("num=%s, den=%s", num, den)
        logger.debug("integral bound=%s", res)
        return res

    def series0(self, ord):
        Pol = self._Poly_IC # XXX should be IR eventually
        res = Pol.zero()
        for num, den_facto in self.fracs:
            den = prod((lin**mult for lin, mult in den_facto), Pol.one())
            res += num._mul_trunc_(den.inverse_series_trunc(ord), ord)
        return res

    def __mul__(self, pol):
        """
        Multiplication by a polynomial.

        Note that this does not change the radius of convergence.
        """
        assert isinstance(pol, Polynomial)
        return RationalMajorant([(pol*num, den) for num, den in self.fracs])

class HyperexpMajorant(MajorantSeries):
    r"""
    A formal power series of the form rat1(z)·exp(int(rat2(ζ), ζ=0..z)), with
    nonnegative coefficients.

    The fraction rat1 is represented in the form z^shift*num(z)/den(z).

    TESTS::

        sage: from ore_algebra.analytic.bounds import *
        sage: Pol.<z> = RBF[]
        sage: one = Pol.one().factor()
        sage: den0 = Factorization([(1-z,1)])
        sage: integrand = RationalMajorant([(4+4*z, one), (z^2, den0)])
        sage: den = Factorization([(1/3-z, 1)])
        sage: maj = HyperexpMajorant(integrand, Pol.one(), den); maj
        (1.00... * (-z + [0.333...])^-1)*exp(int(4.0...
                                                + 4.0...*z + z^2/(-z + 1.0...)))
        sage: maj.cvrad
        [0.333...]
        sage: maj.bound_series(0, 4)
        ([336.000...])*z^3 + ([93.000...])*z^2 + ([21.000...])*z + [3.000...]
        sage: maj._test()
        sage: maj*=z^20
        sage: maj
        (z^20*1.00... * (-z + [0.333...])^-1)*exp(int(4.000...
                                            + 4.000...*z + z^2/(-z + 1.000...)))
        sage: maj._test()
    """

    # The choice of having the integral start at zero (i.e., choosing the
    # exponential part that is equal to one at 0, instead of a constant
    # multiple) is arbitrary, in the sense that the exponential part appearing
    # in the “homogeneous” part of the majorant will be compensated by the one
    # in the denominator of the integrand in the variation-of-constants
    # formula. Of course, the choice needs to be consistent.

    def __init__(self, integrand, num, den, shift=0):
        assert isinstance(integrand, RationalMajorant)
        assert isinstance(num, Polynomial)
        assert isinstance(den, Factorization)
        assert isinstance(shift, int) and shift >= 0
        cvrad = integrand.cvrad.min(_zero_free_rad([pol for (pol, m) in den]))
        super(self.__class__, self).__init__(integrand.variable_name, cvrad)
        self.integrand = integrand
        self.num = num
        self.den = den
        self.shift = shift

    def __repr__(self):
        if self.shift > 0:
            shift_part = "{}^{}*".format(self.num.variable_name(), self.shift)
        else:
            shift_part = ""
        return "({}{})*exp(int({}))".format(shift_part, (~self.den)*self.num,
                                                                self.integrand)

    @cached_method
    def _den_expanded(self):
        return prod(pol**m for (pol, m) in self.den)

    def exp_part_series0(self, ord):
        # This uses the fact that the integral in the definition of self starts
        # at zero!
        return self.integrand.series0(ord-1).integral()._exp_series(ord)

    def bound_series(self, rad, ord):
        r"""
        TESTS::

            sage: from ore_algebra import *
            sage: from ore_algebra.analytic.bounds import DiffOpBound
            sage: Dops, x, Dx = DifferentialOperators()
            sage: maj = DiffOpBound(Dx-1)(10)
            sage: maj.bound(RBF(1000))
            [1.97007111401705e+434 +/- ...]
        """
        # Compute the derivatives “by automatic differentiation”. This is
        # crucial for performance with operators of large order.
        Pol = PolynomialRing(IC, self.variable_name) # XXX: should be IR
        pert_rad = Pol([rad, 1])
        shx_ser = pert_rad.power_trunc(self.shift, ord)
        num_ser = Pol(self.num).compose_trunc(pert_rad, ord) # XXX: remove Pol()
        den_ser = Pol(self._den_expanded()).compose_trunc(pert_rad, ord)
        assert num_ser.parent() is den_ser.parent()
        rat_ser = (shx_ser._mul_trunc_(num_ser, ord)
                          ._mul_trunc_(den_ser.inverse_series_trunc(ord), ord))
        # Majorant series for the integral. Note that we need the constant term
        # here, since we assume in exp_part_series0 and elsewhere that the
        # exponential part is one at rad=0.
        int_ser = self.integrand.bound_integral(rad, ord)
        exp_ser = int_ser._exp_series(ord)
        ser = rat_ser._mul_trunc_(exp_ser, ord)
        return ser

    def __imul__(self, pol):
        r"""
        IN-PLACE multiplication by a polynomial. Use with care!

        Note that this does not change the radius of convergence.
        """
        valuation = pol.valuation() if pol else 0
        self.shift += valuation
        self.num *= (pol >> valuation)
        return self

    def __irshift__(self, n):
        r"""
        IN-PLACE multiplication by x^n. Use with care!
        """
        self.shift += n
        return self

######################################################################
# Majorants for reciprocals of polynomials (“denominators”)
######################################################################

def graeffe(pol):
    r"""
    Compute the Graeffe iterate of a polynomial.

    EXAMPLES:

        sage: from ore_algebra.analytic.bounds import graeffe
        sage: Pol.<x> = QQ[]

        sage: pol = 6*x^5 - 2*x^4 - 2*x^3 + 2*x^2 + 1/12*x^2^2
        sage: sorted(graeffe(pol).roots(CC))
        [(0.000000000000000, 2), (0.110618733062304 - 0.436710223946931*I, 1),
        (0.110618733062304 + 0.436710223946931*I, 1), (0.547473953628478, 1)]
        sage: sorted([(z^2, m) for z, m in pol.roots(CC)])
        [(0.000000000000000, 2), (0.110618733062304 - 0.436710223946931*I, 1),
        (0.110618733062304 + 0.436710223946931*I, 1), (0.547473953628478, 1)]

    TESTS::

        sage: graeffe(CIF['x'].zero())
        0
        sage: graeffe(RIF['x'](-1/3))
        0.1111111111111111?
    """
    deg = pol.degree()
    Parent = pol.parent()
    pol_even = Parent([pol[2*i] for i in xrange(deg/2+1)])
    pol_odd = Parent([pol[2*i+1] for i in xrange(deg/2+1)])
    graeffe_iterate = (-1)**deg * (pol_even**2 - (pol_odd**2).shift(1))
    return graeffe_iterate

def abs_min_nonzero_root(pol, tol=RR(1e-2), min_log=RR('-inf'), prec=None):
    r"""
    Compute an enclosure of the absolute value of the nonzero complex root of
    ``pol`` closest to the origin.

    INPUT:

    - ``pol`` -- Nonzero polynomial.

    - ``tol`` -- An indication of the required relative accuracy (interval
      width over exact value). It is currently *not* guaranteed that the
      relative accuracy will be smaller than ``tol``.

    - ``min_log`` -- Return a bound larger than ``2^min_log``. The function
      may loop if there is a nonzero root of modulus bounded by that value.

    - ``prec`` -- working precision.

    ALGORITHM:

    Essentially the method of Davenport & Mignotte (1990).

    EXAMPLES::

        sage: from ore_algebra.analytic.bounds import abs_min_nonzero_root
        sage: Pol.<z> = QQ[]
        sage: pol = 1/10*z^3 + z^2 + 1/7
        sage: sorted(z[0].abs() for z in pol.roots(CC))
        [0.377695553183559, 0.377695553183559, 10.0142451007998]

        sage: abs_min_nonzero_root(pol)
        [0.38 +/- 3.31e-3]

        sage: abs_min_nonzero_root(pol, tol=1e-10)
        [0.3776955532 +/- 2.41e-11]

        sage: abs_min_nonzero_root(pol, min_log=-1.4047042967)
        [0.3776955532 +/- 2.41e-11]

        sage: abs_min_nonzero_root(pol, min_log=-1.4047042966)
        Traceback (most recent call last):
        ...
        ValueError: there is a root smaller than 2^(-1.40470429660000)

        sage: abs_min_nonzero_root(pol, tol=1e-50)
        [0.3776955531835593496507263902642801708344727099333...]

        sage: abs_min_nonzero_root(Pol.zero())
        Traceback (most recent call last):
        ...
        ValueError: expected a nonzero polynomial

    TESTS::

        sage: abs_min_nonzero_root(CBF['x'].one())
        +Infinity
        sage: abs_min_nonzero_root(CBF['x'].gen())
        +Infinity
        sage: abs_min_nonzero_root(CBF['x'].gen() - 1/3)
        [0.33 +/- 3.34e-3]

    An example where the ability to increase the precision is used::

        sage: from ore_algebra import *
        sage: from ore_algebra.analytic.bounds import DiffOpBound
        sage: Dops, x, Dx = DifferentialOperators()
        sage: dop = (x^2 + 10*x + 50)*Dx^2 + Dx + 1
        sage: import logging; logging.basicConfig()
        sage: logger = logging.getLogger('ore_algebra.analytic.bounds')
        sage: logger.setLevel(logging.DEBUG)
        sage: maj = DiffOpBound(dop, bound_inverse="simple")
        INFO:...
        DEBUG:ore_algebra.analytic.bounds:failed to bound the roots...
        ...
        sage: logger.setLevel(logging.WARNING)
    """
    if prec is None:
        prec = IR.precision()
    tol = RealField(prec)(tol)
    myIR = type(IR)(prec)
    myRIF = type(RIF)(prec) # XXX: could use balls with recent arb (> intersect)
    if pol.is_zero():
        raise ValueError("expected a nonzero polynomial")
    pol >>= pol.valuation()
    deg = pol.degree()
    if deg == 0:
        return infinity
    pol = pol/pol[0]
    mypol = pol.change_ring(myIR.complex_field())
    i = 0
    lg_rad = myRIF(-infinity, infinity)        # left-right intervals because we
    encl = myRIF(1, 2*deg).log(2)              # compute intersections
    neg_infty = myRIF('-inf')
    while (safe_le(lg_rad.lower(rnd='RNDN'), min_log)
              # *relative* error on 2^lg_rad
           or safe_gt(lg_rad.absolute_diameter(), tol)):
        prev_lg_rad = lg_rad
        # The smallest root of the current mypol is between 2^(-1-m) and
        # (2·deg)·2^(-1-m), cf. Davenport & Mignotte (1990), Grégoire (2012).
        m = myIR(-infinity).max(*(mypol[k].abs().log(2)/k
                                for k in xrange(1, deg+1)))
        lg_rad = (-(1 + myRIF(m)) + encl) >> i
        lg_rad = prev_lg_rad.intersection(lg_rad)
        stalled = (lg_rad.endpoints() == prev_lg_rad.endpoints())
        if (neg_infty in lg_rad or lg_rad.is_NaN() or stalled):
            prec *= 2
            logger.debug("failed to bound the roots of %s, "
                    "retrying with prec=%s bits", pol, prec)
            return abs_min_nonzero_root(pol, tol, min_log, prec)
        logger.log(logging.DEBUG - 1, "i = %s\trad ∈ %s\tdiam=%s",
                i, lg_rad.exp2().str(style='brackets'),
                lg_rad.absolute_diameter())
        # detect gross input errors (this does not prevent all infinite loops)
        if safe_le(lg_rad.upper(rnd='RNDN'), min_log):
            raise ValueError("there is a root smaller than 2^({})"
                             .format(min_log))
        mypol = graeffe(mypol)
        i += 1
    res = myIR(2)**myIR(lg_rad)
    if not safe_le(2*res.rad_as_ball()/res, myIR(tol)):
        logger.debug("required tolerance may not be met")
    return res

######################################################################
# Bounds on rational functions of n
######################################################################

@cached_function # XXX: tie life to a suitable object
def _complex_roots(pol):
    if not pol.parent() is QQ: # QQ typical (ordinary points)
        pol = pol.change_ring(QQbar)
    return [(IC(rt), mult) for rt, mult in pol.roots(CIF)]

# Possible improvement: better take into account the range of derivatives
# needed at each step.
class RatSeqBound(object):
    r"""
    Bounds on the tails of a.e. rational sequences and their derivatives.

    Consider a vector of rational sequences sharing a single denominator,

        f(n) = nums(n)/den(n) = [num[i](n)/den(n)]_i.

    We assume that den is monic and deg(nums) < deg(den). Let

        ref(n) = sum[t=0..ord-1](|n*F[t](n)/t!|)

    where

                  ⎧ f^(t)(n),                           n ∉ exceptions,
        F[t](n) = ⎨ (d/dX)^t(num(n+X)/(X^{-m}·den(n+X)))(X=0)),
                  ⎩                                     exceptions[n] = m

    (the first formula is the specialization to m = 0 of the second one).

    An instance of this class represents a vector of bounds b(n) such that

        ∀ k ≥ n,   |ref(k)| ≤ b(n)  (componentwise).

    (Note: the entries of b(n) are not guaranteed to be nonincreasing.)

    Such bounds appear as coefficients in the parametrized majorant series
    associated to differential operators, see the class DiffOpBound. The
    ability to bound a sum of derivatives rather than a single rational
    function is useful to support logarithmic solutions at regular singular
    points. Vectors of bounds are supported purely for performance reasons: it
    helps avoiding redundant computations on the indices and denominators.

    TODO: extend to allow ord to vary?

    ALGORITHM:

    This version essentially bounds the numerators (from above) and the
    denominator (from below) separately. This simple strategy works well in the
    typical case where the indicial equation has only small roots, and makes it
    easy to share part of the computation over a vector of bounds. In the
    presence of, e.g., large real roots, however, it is not much better than
    waiting to get past the largest root.

    See the git history for a tighter but more expensive alternative.

    EXAMPLES::

        sage: Pols.<n> = QQ[]
        sage: from ore_algebra.analytic.bounds import RatSeqBound

        sage: bnd = RatSeqBound([Pols(1)], n*(n-1)); bnd
        bound(1/(n^2 - n), ord=1)
            = +infinity, +infinity, 1.0000, 0.50000, 0.33333, 0.25000, 0.20000,
            0.16667, ..., ~1.00000*n^-1
        sage: [bnd(k)[0] for k in range(5)]
        [[+/- inf], [+/- inf], [1.000...], [0.500...], [0.333...]]
        sage: bnd._test()
        sage: bnd.plot()
        Graphics object...

        sage: bnd = RatSeqBound([-n], n*(n-3), {0:1, 3:1}, ord=3); bnd
        bound(-1/(n - 3), ord=3)
            = 1842.5, 1842.5, 141.94, 12.000, 12.000, 4.3750, 2.8889, 2.2969,
            ..., ~1.00000
            [1842.5...]    for  n <= 0,
            [12.000...]    for  n <= 3
        sage: [(bnd.ref(k)[0], bnd(k)[0]) for k in range(5)]
        [(0,          [1842.5...]),
         (0.875...,   [1842.5...]),
         (6.000...,   [141.94...]),
         ([3.000...], [12.000...]),
         (12.000...,  [12.000...])]
        sage: bnd._test()

        sage: RatSeqBound([n], n, {})
        Traceback (most recent call last):
        ...
        ValueError: expected deg(num) < deg(den)

        sage: bnd = RatSeqBound([n^5-100*n^4+2], n^3*(n-1/2)*(n-2)^2,
        ....:                   {0:3, 2:2})
        sage: bnd._test(200)
        sage: bnd.plot()
        Graphics object...

        sage: bndvec = RatSeqBound([n, n^2, n^3], (n+1)^4)
        sage: for bnd in bndvec:
        ....:     bnd._test()

    TESTS::

        sage: RatSeqBound([Pols(3)], n)(10)
        [3.000...]
        sage: QQi.<i> = QuadraticField(-1, 'i')
        sage: RatSeqBound([Pols(1)], n+i)._test()
        sage: RatSeqBound([-n], n*(n-3), {3:1})._test()
        sage: RatSeqBound([-n], n*(n-3), {0:1})._test()
        sage: RatSeqBound([-n], n*(n-3), {0:1,3:1})._test()
        sage: RatSeqBound([CBF(i)*n], n*(n-QQbar(i)), {0:1})._test()
        sage: RatSeqBound([QQi['n'](3*i+1)], n + (i-1)/3, {})._test()

        sage: from ore_algebra.analytic.bounds import _test_RatSeqBound
        sage: _test_RatSeqBound() # long time
        sage: _test_RatSeqBound(base=QQi, number=3, deg=3) # long time
    """

    def __init__(self, nums, den, exceptions={}, ord=None):
        r"""
        INPUT:

        - den - polynomial with complex coefficients,
        - nums - list of polynomials with complex coefficients, each
          with deg(num) < deg(den);
        - exceptions - dictionary {zero: multiplicity} for a subset of the
          natural integer zeros of den[*],  typically
            - either the full list of integer zeros (or a “right segment”), in
              the context of evaluations at regular singular points,
            - or empty, if one is not interested in derivatives and willing to
              do with an infinite bound up to the rightmost integer zero of
              den.

        In the main application this is intended for, den is the indicial
        equation of a differential operator and the nums are coefficients of
        related recurrence operators, both shifted so that some root of
        interest of the indicial equation is mapped to zero.

        [*] At least part of the code actually works for more general
            values of the exceptions parameter.
        """
        deg = den.degree()
        if any(num.degree() >= deg for num in nums):
            raise ValueError("expected deg(num) < deg(den)")
        if ord is None:
            ord = 1 + sum(exceptions.values())
        self.nums = []
        self._ivnums = []
        self._rcpq_nums = []
        assert den.is_monic()
        self.den = den
        self._ivden = den.change_ring(IC)
        self._rcpq_den = den.change_ring(IC).reverse()
        self.ord = ord
        self.exn = exceptions
        self._Pol = self._rcpq_den.parent()
        self._pol_class = self._Pol.Element
        self.extend(nums)

    def extend(self, nums):
        r"""
        Add new sequences to this bound, without changing the rest of the data.

        Use with care!
        """
        self.nums.extend(nums)
        ivnums = [num.change_ring(IC) for num in nums]
        self._ivnums.extend(ivnums)
        deg = self.den.degree()
        # rcpq_num/rcpq_den = (1/n)*rat(1/n)
        self._rcpq_nums.extend([num.reverse(deg-1) for num in ivnums])
        self._stairs.clear_cache()

    def __len__(self):
        return len(self.nums)

    def entries_repr(self, type):
        if type == "asympt":
            fmt = "{asympt}"
        elif type == "short":
            fmt = "bound({rat}, ord={ord})"
        elif type == "full":
            fmt  = "bound({rat}, ord={ord})\n"
            fmt += "    = {list},\n"
            fmt += "      ..., {asympt}"
            fmt += "{stairs}"
        n = self.den.variable_name()
        bnds = zip(*(self(k) for k in range(8)))
        stairs = self._stairs(len(self))
        dscs = []
        assert len(self.nums) == len(bnds) == len(stairs)
        for (num, bnd, seq_stairs) in zip(self.nums, bnds, stairs):
            lim = abs(ComplexBallField(20)(num.leading_coefficient()))
            deg = num.degree() - self.den.degree() + 1
            asymptfmt = "~{lim}" if deg == 0 else "~{lim}*n^{deg}"
            stairsstr = ',\n'.join(
                    ["    {}\tfor  {} <= {}".format(val, n, edge)
                     for edge, val in seq_stairs])
            dscs.append(
                fmt.format(
                    rat=num/self.den,
                    ord=self.ord,
                    list=", ".join(str(b.n(20)) for b in bnd),
                    asympt=asymptfmt.format(lim=lim, deg=deg),
                    stairs=stairsstr if seq_stairs else ""))
        return dscs

    def __repr__(self):
        return "\n".join(self.entries_repr("full"))

    def __getitem__(self, i):
        return RatSeqBound([self.nums[i]], self.den, self.exn, self.ord)

    @cached_method
    def _den_data(self):
        r"""
        Shared part of the computation of _lbound_den(n) for varying n.

        OUTPUT:

        A lower bound on self.den/n^r (where r = deg(self.den)) in the format
        that _lbound_den expects. That is, a list of tuples (root, mult, n_min,
        global_lbound) where
        - root ranges over a subset of the roots of den;
        - mult is the multiplicity of root in den;
        - n_min is an integer s.t. |1-root/n| is nondecreasing for n ≥ nmin;
        - global_lbound is a real (ball) s.t. |1-root/n| ≥ global_lbound for
          all n ∈ ⟦1,∞) ∖ exceptions (in particular, for n < n_min).

        Often (but not always), all integer roots of den will belong to the
        exceptional set, and in this case the returned global_lbound will be
        strictly positive.
        """
        den_data = []
        for root, mult in _complex_roots(self.den):
            re = root.real()
            # When Re(α) ≤ 0, the sequence |1-α/n| decreases to 1.
            if safe_le(re, IR.zero()):
                continue
            # Otherwise, it first decreases to its minimum (which may be 0 if α
            # is an integer), then increases to 1. We compute the minimum and a
            # value of n after which the sequence is nondecreasing. The
            # interval re may contain zero, but it is okay to replace it by an
            # upper bound since the (lower bound on the) distance to 1
            # decreases when re increases.
            crit_n = root.abs()**2/re.above_abs()
            ns = srange(crit_n.lower().floor(), crit_n.upper().ceil() + 1)
            n_min = ns[-1]
            # We skip exceptional indices among the candidates in the
            # computation of the global lower bound, and consider the adjacent
            # integers above and below instead. In particular, when the current
            # root is equal to an exceptional index, the global minimum over ℕ
            # is zero, but we want a nonzero lower bound over ℕ ∖ exceptions.
            # There can be several consecutive exceptional indices (this is
            # even quite typical).
            while ns[-1] in self.exn:
                ns.append(ns[-1] + 1) # append to avoid overwriting ns[0]
            while ns[0] in self.exn:
                ns[0] -= 1
            global_lbound = IR.one().min(*(
                    (IC.one() - root/n).abs()
                    for n in ns if n >= 1 and not n in self.exn))
            global_lbound = global_lbound.below_abs()**mult # point ball
            den_data.append((root, mult, n_min, global_lbound))
        return den_data

    def _lbound_den(self, n):
        r"""
        A lower bound on prod[den(α) = 0](|1-α/k|) valid for all k ≥ n with
        n, k ∈ ℕ ∖ exceptions.
        """
        assert n not in self.exn
        if n == 0:
            return IR.zero() # _den_data() assumes n ≥ 1
        res = IR.one()
        for root, mult, n_min, global_lbound in self._den_data():
            if n < n_min:
                # note that global_lbound already takes mult into account
                res *= global_lbound
            else:
                res *= abs((IC.one() - root/n))**mult
        return res

    def _bound_rat(self, n, ord):
        r"""
        A componentwise bound on the vector ref[ord](k), valid for all k ≥ n
        with n, k ∉ exceptions.

        When ord = 0, this method simply evaluates the reciprocal polynomials
        of nums and den, rescaled by a suitable power of n, on an interval of
        the form [0,1/n]. (It works for exceptional indices, but doesn't do
        anything clever to take advantage of them.) More generally, a similar
        evaluation on an interval jet of the form [0,1/n] + ε + O(ε^ord)
        yields bounds for the derivatives as well.
        """
        assert n not in self.exn
        iv = IR.zero().union(~IR(n))
        # jet = 1/(n+ε) = n⁻¹/(1+n⁻¹ε)
        jet0 = self._pol_class(self._Pol, [IR.one(), iv])
        jet1 = jet0.inverse_series_trunc(ord)
        jet = iv*jet1
        # Most expensive part. Perhaps consider simplifying rcpq_num, rcpq_den
        # by bounding the high-degree terms for large n???
        nums = [num.compose_trunc(jet, ord) for num in self._rcpq_nums]
        den = self._rcpq_den.compose_trunc(jet, ord)
        invabscst = IR.one()
        if den[0].contains_zero():
            # Replace the constant coefficient by a tighter bound (in
            # particular, one that should be finite even in the presence of
            # poles at exceptional or non-integer indices). More precisely,
            # since den has complex coefficients, we use the lower bound on the
            # absolute value of den(0) to compute a complex ball enclosing
            # 1/den(0), and multiply the computed den by this ball. We will
            # later multiply the complete bound by the same value.
            lb = self._lbound_den(n)
            invabscst = IR.zero().union(~lb)
            # invabscst = IR(~RIF(self._lbound_den(n).lower(), lb.upper()))
            invcst = IC.zero().add_error(invabscst)
            den = 1 + (invcst*(den >> 1) << 1)
            logger.debug("lb=%s, refined den=%s", lb, den)
        # num/den = invcst⁻¹·(n+ε)·f(1/(n+ε))
        # ser0 = (1+ε/n)⁻¹/den
        # ser = ser0·num = invcst⁻¹·n·f(n+ε)
        invden = den.inverse_series_trunc(ord)
        ser0 = jet1._mul_trunc_(invden, ord)
        bounds = []
        for num in nums:
            ser = ser0._mul_trunc_(num, ord)
            bound = (invabscst*sum(c.above_abs() for c in ser)).above_abs()
            # logger.debug(lazy_string(lambda: "bound[%s](%s) = %s = %s" % (
            # num, n, "+".join([str(invabscst*c.above_abs()) for c in ser]),
            # bound)))
            if not bound.is_finite():
                bound = IR(infinity) # replace NaN by +∞ (as max(NaN, 42) = 42)
            bounds.append(bound)
        return bounds

    @cached_method
    def _stairs(self, count):
        r"""
        Shared part of the computation of _bound_exn(n) for varying n.

        OUTPUT:

        A list whose element of index i is a list of pairs (edge, val), ordered
        by increasing edge, and such that |ref(n)[i]| ≤ val for all n ≥ edge.
        """
        # consistency check, we need to recompute or at least extend the stairs
        # each time the sequence of numerators is extended
        assert count == len(self.nums)
        if not self.exn:
            return [[]]*len(self.nums)
        stairs = [[(infinity, IR.zero())] for _ in self.nums]
        for n in sorted(self.exn, reverse=True):
            # We want the bound to hold for ordinary k ≥ n too, so we take the
            # max of the exceptional value and the next ordinary index.
            n1 = next(n1 for n1 in itertools.count(n) if n1 not in self.exn)
            refs = self.ref(n)
            rats = self._bound_rat(n1, self.ord)
            assert len(refs) == len(rats) == len(stairs) == len(self.nums)
            for (ref, rat, seq_stairs) in zip(refs, rats, stairs):
                val = ref.max(rat)
                if val.upper() > seq_stairs[-1][1].upper():
                    seq_stairs.append((n, val))
        for seq_stairs in stairs:
            seq_stairs.reverse()
            # remove (∞,0) (faster and permits testing "stairs == []")
            seq_stairs.pop()
        return stairs

    def _bound_exn(self, n):
        r"""
        A list of non-increasing staircase functions defined on the whole of ℕ
        such that, whenever *n* (sic) is an exceptional index, the inequality
        ref(k) ≤ _bound_exn(n) holds (componentwise) for all k ≥ n (whether
        ordinary or exceptional).

        (The pairs returned by _stairs() correspond to the *upper right* corner
        of each stair: the index associated to a given value is the last time
        this value will be reached by the staircase function _bound_exn().
        One may well have |f[i](n)| > _bound_exn(n)[i] when n is ordinary.)
        """
        # Return the value associated to the smallest step larger than n. (This
        # might be counter-intuitive!)
        def doit(seq_stairs):
            for (edge, val) in seq_stairs:
                if n <= edge:
                    return val
            return IR.zero()
        stairs = self._stairs(len(self.nums))
        return [doit(seq_stairs) for seq_stairs in stairs]

    def __call__(self, n):
        r"""
        The bounds.
        """
        ord = self.ord # XXX: take as parameter???
        bound_exn = self._bound_exn(n)
        if n in self.exn:
            return bound_exn
        else:
            bound_rat = self._bound_rat(n, ord)
            return [b1.max(b2) for b1, b2 in zip(bound_rat, bound_exn)]

    def ref(self, n):
        r"""
        Reference value for a single n.
        """
        ord = self.ord # XXX: take as parameter???
        jet = self._pol_class(self._Pol, [n, 1])
        nums = [num.compose_trunc(jet, ord) for num in self._ivnums]
        mult = self.exn.get(n, 0)
        # den has a root of order mult at n, so den(pert) = O(X^mult), but the
        # computed value might include terms of degree < mult with interval
        # coefficients containing zero
        den = self._ivden.compose_trunc(jet, ord + mult) >> mult
        invden = den.inverse_series_trunc(ord)
        sers = [num._mul_trunc_(invden, ord) for num in nums]
        my_n = IR(n)
        return [my_n*sum((c.abs() for c in ser), IR.zero()) for ser in sers]

    def plot(self, rng=xrange(40)):
        r"""
        Plot this bound and its reference function.

        The vector of nums/bounds must have length one.

        EXAMPLES::

            sage: from ore_algebra.analytic.bounds import RatSeqBound
            sage: Pols.<n> = QQ[]
            sage: i = QuadraticField(-1).gen()
            sage: bnd = RatSeqBound(
            ....:     [CBF(i)*n+42], n*(n-3)*(n-i-20), {0:1,3:1})
            sage: bnd.plot()
            Graphics object consisting of ... graphics primitives
            sage: bnd.plot(xrange(30))
            Graphics object consisting of ... graphics primitives
        """
        if len(self.nums) != 1:
            raise NotImplementedError("expected a single sequence")
        from sage.plot.plot import list_plot
        p1 = list_plot(
                [(k, RR(self.ref(k)[0].upper()))
                    for k in rng if self.ref(k)[0].is_finite()],
                plotjoined=True, color='black', scale='semilogy')
        # Plots come up empty when one of the y-coordinates is +∞, so we may as
        # well start with the first finite value.
        rng2 = list(itertools.dropwhile(
            lambda k: self(k)[0].is_infinity(), rng))
        p2 = list_plot(
                [(k, RR(self(k)[0].upper())) for k in rng2],
                plotjoined=True, color='blue', scale='semilogy')
        p3 = list_plot(
                [(k, RR(self._bound_rat(k, self.ord)[0].upper())) for k in rng2
                    if k not in self.exn],
                size=20, color='red', scale='semilogy')
        p4 = list_plot(
                [(k, RR(self._bound_exn(k)[0].upper())) for k in rng],
                size=20, color='gray', scale='semilogy')
        m = max(rng)
        p5 = list_plot([(e, v.upper()) for (e, v) in self._stairs(1)[0]
                                       if e <= m],
                size=60, marker='x', color='gray', scale='semilogy')
        return p1 + p2 + p3 + p4 + p5

    # TODO: add a way to _test() all bounds generated during a given
    # computation
    def _test(self, nmax=100, kmax=10, ordmax=5):
        r"""
        Test that this bound is well-formed and plausibly does bound ref.

        The vector of nums/bounds must have length one.
        """
        if len(self.nums) != 1:
            raise NotImplementedError("expected a single sequence")
        deg = self.den.degree()
        # Well-formedness
        for n, mult in self.exn.iteritems():
            pol = self.den
            for i in range(mult):
                assert pol(n).is_zero()
                pol = pol.derivative()
        # Test _lbound_den()
        for n in range(nmax):
            if n not in self.exn:
                lb = self._lbound_den(n)
                assert not (lb*IR(n)**deg > IC(self.den(n)).abs())
                if n + 1 not in self.exn:
                    assert not (self._lbound_den(n+1) < lb)
        testrange = range(nmax) + [nmax + (1 << k) for k in range(kmax)]
        testrange.reverse()
        # Test _bound_rat()
        ref = [IR(0) for _ in range(ordmax + 1)]
        for n in testrange:
            if n not in self.exn:
                rat = self.nums[0]/self.den
                ref_n = IR(0)
                for ord in range(ordmax + 1):
                    ref_n += rat(IC(n)).abs()/ZZ(ord).factorial()
                    ref[ord] = ref[ord].max(ref_n)
                    bound = self._bound_rat(n, ord+1)[0]
                    assert not (bound < ref[ord])
                    rat = rat.derivative()
        # Test the complete bound
        ref = IR(0)
        for n in testrange:
            n = ref.max(self.ref(n)[0])
            assert not (self(n)[0] < ref)

@random_testing
def _test_RatSeqBound(number=10, base=QQ, deg=20, verbose=False):
    r"""
    Randomized testing helper.

    EXAMPLES::

        sage: from ore_algebra.analytic.bounds import _test_RatSeqBound
        sage: _test_RatSeqBound(number=1, deg=4, verbose=True, seed=0)
        num = -1/2
        den = n^4 - 3043/285*n^3 - 5879/380*n^2 - 5513/1140*n + 1/19
        exns = {12: 1}
    """
    from sage.combinat.subset import Subsets
    Pols, n = PolynomialRing(base, 'n').objgen()
    PolsZ = PolynomialRing(ZZ, 'n')
    assert deg >= 1
    for _ in range(number):
        dlin = ZZ.random_element(deg) # < deg
        drnd = ZZ.random_element(1, deg - dlin + 1)
        dnum = ZZ.random_element(dlin + drnd)
        num = Pols.random_element(degree=dnum)
        den0 = prod((PolsZ.random_element(degree=1) for _ in range(dlin)),
                    PolsZ.one())
        den = (den0 * Pols.random_element(degree=drnd)).monic()
        try:
            roots = den.numerator().roots(ZZ)
        except TypeError:
            # If sage is unable to find the roots over this base ring, test
            # with the part that is guaranteed to factor completely over ℤ.
            roots = den0.roots(ZZ)
        roots = [(r, m) for (r, m) in roots if r >= 0]
        exns = dict(Subsets(roots).random_element())
        if verbose:
            print("num = {}\nden = {}\nexns = {}".format(num, den, exns))
        bnd = RatSeqBound([num], den, exns)
        bnd._test()

################################################################################
# Bounds for differential equations
################################################################################

def bound_polynomials(pols):
    r"""
    Compute a common majorant polynomial for the polynomials in ``pol``.

    Note that this returns a _majorant_, not some kind of enclosure.

    TESTS::

        sage: from ore_algebra.analytic.bounds import bound_polynomials
        sage: Pol.<z> = PolynomialRing(QuadraticField(-1, 'i'), sparse=True)
        sage: bound_polynomials([(-1/3+z) << (10^10), (-2*z) << (10^10)])
        2.000...*z^10000000001 + [0.333...]*z^10000000000
        sage: bound_polynomials([Pol(0)])
        0
        sage: bound_polynomials([])
        Traceback (most recent call last):
        ...
        IndexError: list index out of range
    """
    assert isinstance(pols, list)
    PolyIC = pols[0].parent().change_ring(IC)
    deg = max(pol.degree() for pol in pols)
    val = min(deg, min(pol.valuation() for pol in pols))
    pols = [PolyIC(pol) for pol in pols] # TBI
    order = Integer(len(pols))
    PolyIR = PolyIC.change_ring(IR)
    def coeff_bound(n):
        return IR.zero().max(*(
            pols[k][n].above_abs()
            for k in xrange(order)))
    maj = PolyIR([coeff_bound(n) for n in xrange(val, deg + 1)])
    maj <<= val
    return maj

class DiffOpBound(object):
    r"""
    A “bound” on the “inverse” of a differential operator at a regular point.

    A DiffOpBound can be thought of as a sequence of formal power series

        v[n](z) = 1/den(z) · exp ∫ (pol[n](z) + cst·z^ℓ·num[n](z)/den(z))

    where

    * cst is a real number,
    * den(z) is a polynomial with constant coefficients,
    * pol[n](z) and num[n](z) are polynomials with coefficients depending on n
      (given by RatSeqBound objects), and ℓ >= deg(pol[n]).

    These series can be used to bound the tails of logarithmic power series
    solutions y(z) belonging to a certain subspace (see the documentation of
    __init__() for details) of dop(y) = 0. More precisely, write

        y(z) - ỹ(z) = z^λ·(u[0](z)/0! + u[1](z)·log(z)/1! + ···)

    where y(z) is a solution of self.dop (in the correct subspace, with
    λ = self.leftmost) and ỹ(z) is its truncation to O(z^n1). Then, for
    suitable n0 ∈ ℕ and p(z) ∈ ℝ_+[z], the series ŷ(z) = v[n0](z)·p(z) is a
    common majorant of u[0], u[1], ...

    In the typical situation where n0 ≤ n1 and y(z) does not depend on initial
    conditions “past” n1, a polynomial p(z) of valuation at least n1 with this
    property can be computed using the methods normalized_residual() and rhs().
    Variants with different p hold in more general settings. See their
    documentation of normalized_residual() and rhs() for more information.

    Note that multiplying dop by a rational function changes p(z).

    DiffOpBounds are refinable: calling the method refine() will try to replace
    the parametrized series v[n](z) by one giving tighter bounds. The main
    effect of refinement is to increase the degree of the polynomial part. This
    can be done several times, but repeated calls to refine() quickly become
    expensive.

    EXAMPLES::

        sage: from ore_algebra import *
        sage: from ore_algebra.analytic.bounds import *
        sage: Dops, x, Dx = DifferentialOperators()

    A majorant sequence::

        sage: maj = DiffOpBound((x^2 + 1)*Dx^2 + 2*x*Dx, pol_part_len=0)
        sage: print(maj.__repr__(asympt=False))
        1.000.../((-x + [0.994...])^2)*exp(int(POL+1.000...*NUM/(-x + [0.994...])^2))
        where
        POL=0,
        NUM=bound(0, ord=1)*z^0 +
        bound((-2.000...*n + 2.000...)/(n^2 - n), ord=1)*z^1

    A majorant series extracted from that sequence::

        sage: maj(3)
        (1.00... * (-x + [0.994...])^-2)*exp(int([3.000...]...)^2)))

    An example with a nontrivial polynomial part::

        sage: dop = (x+1)*(x^2+1)*Dx^3-(x-1)*(x^2-3)*Dx^2-2*(x^2+2*x-1)*Dx
        sage: DiffOpBound(dop, pol_part_len=3)
        1.000.../((-x + [0.9965035284306323 +/- 2.07e-17])^3)*exp(int(POL+1.000...*NUM/(-x + [0.9965035284306323 +/- 2.07e-17])^3)) where
        POL=~6.000...*z^0 + ~3.000...*z^1 + ~5.000...*z^2,
        NUM=~7.000...*z^3 + ~2.000...*z^4 + ~5.000...*z^5

    Refining::

        sage: from ore_algebra.analytic.examples import fcc
        sage: maj = DiffOpBound(fcc.dop5)
        sage: maj.maj_den
        (-z + [0.2047...])^13
        sage: maj.maj_den.value()(1/10)
        [1.82513661e-13 +/- 5.50e-22]
        sage: maj.refine()
        sage: maj.maj_den.value()(1/10)
        [436565.0...]
        sage: maj.majseq_pol_part(10)
        [[41.256...], [188.43...]]
        sage: maj.refine()
        sage: maj.majseq_pol_part(10)
        [[41.256...], [188.43...], [920.6...], [4518.9...]]

    TESTS::

        sage: print(DiffOpBound(Dx - 1, pol_part_len=0).__repr__(asympt=False))
        1.000.../(1.000...)*exp(int(POL+1.000...*NUM/1.000...))
        where
        POL=0,
        NUM=bound(-1.000.../n, ord=1)*z^0

        sage: QQi.<i> = QuadraticField(-1)
        sage: for dop in [
        ....:     # orders <= 1 are not supported
        ....:     Dx, Dx - 1, 1/1000*Dx - 1, i*Dx, Dx + i, Dx^2,
        ....:     (x^2 + 1)*Dx^2 + 2*x*Dx,
        ....:     Dx^2 - x*Dx
        ....: ]:
        ....:     DiffOpBound(dop)._test()

        sage: for l in xrange(10):
        ....:     DiffOpBound(Dx - 5*x^4, pol_part_len=l)._test()
        ....:     DiffOpBound((1-x^5)*Dx - 5*x^4, pol_part_len=l)._test()

        sage: from ore_algebra.analytic.bounds import _test_diffop_bound
        sage: _test_diffop_bound() # long time
    """

    def __init__(self, dop, leftmost=ZZ.zero(), special_shifts=[],
            max_effort=6, pol_part_len=2, bound_inverse="simple"):
        r"""
        Construct a DiffOpBound for a subset of the solutions of dop.

        INPUT:

        * dop: element of K(z)[Dz] (K a number field), with 0 as a regular
          (i.e., ordinary or regular singular) point
        * leftmost: algebraic number
        * special_shifts: list of (shift, mult) pairs, where shift is a
          nonnegative integer and (leftmost + shift) is a root of multiplicity
          mult of the indicial polynomial of dop

        OUTPUT:

        The resulting bound applies to the generalized series solutions of dop
        in z^λ·ℂ[[z]][log(z)], λ = leftmost, with the additional property that
        the maximum power of log(z) in the coefficient of z^n is strictly less
        than the sum of the multiplicities of the elements of special_shifts
        with shift ≤ n.

        .. WARNING::

            Thus, special_shifts can be left to its default value of [] when
            the origin is an ordinary point, but needs to contain all the roots
            of the indicial polynomial in λ + ℕ for a general regular singular
            point.

        The remaining parameters are used to set properties of the DiffOpBound
        object related to the effort/tightness trade-off of the algorithm. They
        have no influence on the semantics of the bound.
        """

        logger.info("bounding local operator...")

        if not dop.parent().is_D():
            raise ValueError("expected an operator in K(x)[D]")
        _, Pols_z, _, dop = dop._normalize_base_ring()
        self._dop_D = dop # only used in argument checking, assertions
        self.dop = dop_T = dop.to_T('T' + Pols_z.variable_name())

        lc = dop_T.leading_coefficient()
        if lc.is_term() and not lc.is_constant():
            raise ValueError("irregular singular operator", dop)

        self._rcoeffs = _dop_rcoeffs_of_T(dop_T, IC)

        self.leftmost = leftmost
        self.special_shifts = dict(special_shifts)

        # XXX Consider switching to an interface where the user simply chooses
        # the initial effort (and refine() accepts an effort value)
        self.bound_inverse = bound_inverse
        self.max_effort = max_effort
        self._effort = 0
        if bound_inverse == "solve":
            self._effort += 1
        if pol_part_len > 2:
            self._effort += ZZ(pol_part_len - 2).nbits()

        self.Poly = Pols_z.change_ring(IR) # TBI
        self.__CPoly = Pols_z.change_ring(IC)
        one = self.Poly.one()
        self.__facto_one = Factorization([(one, 1)], unit=one, sort=False,
                                                     simplify=False)

        self._update_den_bound()
        first_nz, rem_num_nz = self._split_dop(pol_part_len)
        self.alg_idx = self.leftmost + polygen(Pols_z.base_ring(), 'n')
        # indicial polynomial, shifted so that integer roots correspond to
        # series in z^λ·ℂ[[z]][log(z)]
        # (mathematically equal to first_nz[0](self.alg_idx), but the latter
        # has interval coefficients, and we need an exact version to compute
        # the roots)
        z = Pols_z.gen()
        self.ind = self._dop_D.indicial_polynomial(z, z).monic()(self.alg_idx)
        assert self.ind.is_monic()
        assert self.ind.base_ring().is_exact()
        self.majseq_pol_part = RatSeqBound([], self.ind, self.special_shifts)
        self._update_num_bound(pol_part_len, first_nz, rem_num_nz)

    def __repr__(self, asympt=True):
        fmt = ("{cst}/({den})*exp(int(POL+{cst}*NUM/{den})) where\n"
               "POL={pol},\n"
               "NUM={num}\n")
        def pol_repr(ratseqbounds, shift):
            if len(ratseqbounds) == 0:
                return 0
            coeff = ratseqbounds.entries_repr("asympt" if asympt else "short")
            return " + ".join("{}*z^{}".format(c, n + shift)
                              for n, c in enumerate(coeff))
        return fmt.format(
                cst=self.cst, den=self.maj_den,
                num=pol_repr(self.majseq_num, shift=len(self.majseq_pol_part)),
                pol=pol_repr(self.majseq_pol_part, shift=0))

    @cached_method
    def _poles(self):
        lc = self.dop.leading_coefficient()
        try:
            return lc.roots(CIF)
        except NotImplementedError:
            return lc.change_ring(QQbar).roots(CIF)

    def _update_den_bound(self):
        r"""
        Set self.cst, self.maj_den so that cst/maj_den is a majorant series
        of the leading coefficient of dop.
        """
        den = self.dop.leading_coefficient()
        if den.degree() <= 0:
            facs = []
        # below_abs()/lower() to get thin intervals
        elif self.bound_inverse == "simple":
            rad = abs_min_nonzero_root(den).below_abs(test_zero=True)
            facs = [(self.Poly([rad, -1]), den.degree())]
        elif self.bound_inverse == "solve":
            facs = [(self.Poly([IR(iv.abs().lower()), -1]), mult)
                    for iv, mult in self._poles()]
        else:
            raise ValueError("algorithm")
        self.cst = ~abs(IC(den.leading_coefficient()))
        self.maj_den = Factorization(facs, unit=self.Poly.one(),
                                     sort=False, simplify=False)

    def _split_dop(self, pol_part_len):
        r"""
        Split self.dop.monic() into a truncated series in z and a remainder.

        Let lc denote the leading coefficient of dop. This function computes
        two operators first, rem ∈ K[θ][z] such that

            dop·lc⁻¹ = first + rem_num·z^ℓ·lc⁻¹,    deg[z](first) < ℓ

        where ℓ = pol_part_len + 1. Thus, first is the Taylor expansion in z to
        order O(z^ℓ) of dop·lc⁻¹ written with θ on the left.

        In the output, first and rem_num are encoded as elements of a
        commutative polynomial ring K[n][z]. More precisely, θ is replaced by a
        commutative variable n, with the convention that n^i·z^j should be
        mapped to θ^i·z^j with θ on the left when translating back.
        """
        # XXX: This function recomputes the series expansion from scratch every
        # time. Use Newton's method to update it instead?
        Pol_z = self.dop.base_ring().change_ring(IC)
        Pol_zn = PolynomialRing(Pol_z, 'n')
        orddeq = self.dop.order()

        # Compute the initial part of the series expansion.
        lc = self.dop.leading_coefficient()
        # Doing the inversion exactly yields much better bounds (at least when
        # the coefficients do not fit on IC.prec() bits)
        inv = lc.inverse_series_trunc(pol_part_len + 1).change_ring(IC)
        # Including rcoeffs[-1] here actually is redundant: by construction,
        # the only term involving n^ordeq  in first will be 1·n^ordeq·z^0.
        first_zn = Pol_zn([pol._mul_trunc_(inv, pol_part_len + 1)
                           for pol in self._rcoeffs])
        # Force the leading coefficient to one after interval computations
        assert all(pol.contains_zero() for pol in first_zn[orddeq] >> 1)
        first_zn = Pol_zn.gen()**orddeq + first_zn[:orddeq]
        first_nz = _switch_vars(first_zn)
        z = Pol_z.gen(); n = Pol_zn.gen()
        # Would hold in exact arithmetic
        # assert first_nz[0] == self._dop_D.indicial_polynomial(z, n).monic()
        assert all(pol.degree() < self.dop.order() for pol in first_nz >> 1)

        # Now compute rem_num as (dop - first·lc)·z^(-pol_part_len-1)
        dop_zn = Pol_zn(self._rcoeffs)
        # By construction (since lc is the leading coefficient of dop and
        # first_nz = 1·n^orddeq + ···), rem_num_0_zn has degree < orddeq in n.
        # Truncate as the interval subtraction may leave inexact zeros.
        rem_num_0_zn = (dop_zn - first_zn*lc)[:orddeq]
        rem_num_0_nz = _switch_vars(rem_num_0_zn)
        # Would hold in exact arithmetic
        # assert rem_num_0_nz.valuation() >= pol_part_len + 1
        rem_num_nz = rem_num_0_nz >> (pol_part_len + 1)

        return first_nz, rem_num_nz

    def _update_num_bound(self, pol_part_len, first_nz, rem_num_nz):
        old_pol_part_len = len(self.majseq_pol_part)
        # We ignore the coefficient first_nz[0], which amounts to multiplying
        # the integrand by z⁻¹, as prescribed by the theory. Since, by
        # definition, majseq_num starts at the degree following that of
        # majseq_pol_part, it gets shifted as well.
        self.majseq_pol_part.extend([first_nz[i](self.alg_idx)
                for i in xrange(old_pol_part_len + 1, pol_part_len + 1)])
        assert len(self.majseq_pol_part) == pol_part_len
        self.majseq_num = RatSeqBound(
                [pol(self.alg_idx) for pol in rem_num_nz],
                self.ind, self.special_shifts)

    def refine(self):
        # XXX: make it possible to increase the precision of IR, IC
        if self._effort >= self.max_effort:
            logger.debug("majorant no longer refinable")
            return
        self._effort += 1
        logger.info("refining majorant (effort = %s)...", self._effort)
        if self.bound_inverse == 'simple':
            self.bound_inverse = 'solve'
            self._update_den_bound()
        else:
            new_pol_part_len = max(2, 2*self.pol_part_len())
            split = self._split_dop(new_pol_part_len)
            self._update_num_bound(new_pol_part_len, *split)

    def pol_part_len(self):
        return len(self.majseq_pol_part)

    def __call__(self, n):
        r"""
        Return a term v[n] of the majorant sequence.
        """
        maj_pol_part = self.Poly(self.majseq_pol_part(n))
        # XXX: perhaps use sparse polys or add explicit support for a shift
        # in RationalMajorant
        maj_num_pre_shift = self.Poly(self.majseq_num(n))
        maj_num = (self.cst*maj_num_pre_shift) << self.pol_part_len()
        terms = [(maj_pol_part, self.__facto_one), (maj_num, self.maj_den)]
        rat_maj = RationalMajorant(terms)
        # The rational part “compensates” the change of unknown function
        # involving the leading coefficient of the operator.
        maj = HyperexpMajorant(integrand=rat_maj, num=self.Poly(self.cst),
                den=self.maj_den)
        return maj

    @cached_method
    def bwrec(self):
        return local_solutions.backward_rec(self.dop, shift=self.leftmost)

    def normalized_residual(self, n, last, bwrec_nplus=None, Ring=IC):
        r"""
        Compute the “normalized residual” associated to a truncated solution
        of dop(y) = 0.

        Consider a solution

            y(z) = z^λ·sum[i,k](y[i,k]·z^i·log(z)^k/k!)

        of self.dop(y) = 0, and its truncated series expansion

            ỹ(z) = z^λ·sum[i<n,k](y[i,k]·z^i·log(z)^k/k!).

        Denote s = deg[z](dop(z,θ)). The equation

            monic(dop(z=0,θ))(f(z)) = dop(ỹ)

        has at least one solution (exactly one when none of λ+n, λ+n+1, ...,
        λ+n+s-1 is a root of the indicial polynomial dop(z=0,n)). Its
        solutions are of the form

            f(z) = z^(λ+n)·sum[k](f[k](z)·log(z)^k/k!)

        for a finite list [f[0], f[1], ...] of polynomials of degree ≤ s-1.

        This method takes as input the truncation order n and the coefficients

            last = [[y[n-1,0], y[n-1,1], ...],
                    [y[n-2,0], y[n-2,1], ...],
                    ...,
                    [y[n-s,0], y[n-s,1], ...]],

        and returns a list [f[0], f[1], ...] as above.

        In order to avoid redundant computations, is possible to pass as
        additional input the series expansions around λ+n+j (0≤j≤s) of the
        coefficients of the recurrence operator dop(S⁻¹,ν) =
        sum[0≤i≤s](b[i](ν)·S⁻¹) associated to dop.

        The optional Ring parameter makes it possible to choose the coefficient
        domain. It is there for debugging purposes.

        .. WARNING::

            The bound holds for the normalized residual computed using the
            operator ``self.dop``, not the one given as input to ``__init__``.
            These operators differ by a power-of-x factor, which may change the
            normalized residual.

        EXAMPLES::

            sage: from ore_algebra import *
            sage: from ore_algebra.analytic.bounds import *
            sage: Dops, t, Dt = DifferentialOperators(QQ, 't')

        Compute the normalized residual associated to a truncation of the
        exponential series::

            sage: trunc = t._exp_series(5); trunc
            1/24*t^4 + 1/6*t^3 + 1/2*t^2 + t + 1
            sage: maj = DiffOpBound(Dt - 1)
            sage: nres = maj.normalized_residual(5, [[trunc[4]]]); nres
            [[-0.00833333333333333 +/- 5.77e-18]]

        Check that it has the expected properties::

            sage: dopT = (Dt - 1).to_T('Tt'); dopT
            Tt - t
            sage: dopT.map_coefficients(lambda pol: pol[0])(nres[0]*t^5)
            ([-0.0416666666666667 +/- 6.40e-17])*t^5
            sage: (Dt - 1).to_T('Tt')(trunc).change_ring(CBF)
            ([-0.0416666666666667 +/- 4.26e-17])*t^5

        Note that using Dt - 1 instead of θt - t makes a difference in the
        result, since it amounts to a division by t::

            sage: (Dt - 1)(trunc).change_ring(CBF)
            ([-0.0416666666666667 +/- 4.26e-17])*t^4

        TESTS::

            sage: maj = DiffOpBound(Dt^2 + 1)
            sage: trunc = t._sin_series(5) + t._cos_series(5)
            sage: maj._check_normalized_residual(5, [trunc], ZZ.zero(), QQ)
            0

            sage: Pol.<n> = CBF[]
            sage: Jets.<eta> = CBF[]
            sage: bwrec = [n*(n-1), Pol(0), Pol(1)]
            sage: bwrec_nplus = [[Jets(pol(5+i)) for pol in bwrec]
            ....:                for i in [0,1]]
            sage: last = [[trunc[4]], [trunc[3]]]
            sage: (maj.normalized_residual(5, last, bwrec_nplus)
            ....:         == maj.normalized_residual(5, last))
            True

        This operator annihilates t^(1/3)*[1/(1-t)+log(t)^2*exp(t)]+exp(t)::

            sage: dop = ((81*(-1+t))*t^4*(3*t^6-19*t^5+61*t^4-85*t^3+106*t^2
            ....: -22*t+28)*Dt^5-27*t^3*(36*t^8-315*t^7+1346*t^6-3250*t^5
            ....: +4990*t^4-5545*t^3+2788*t^2-1690*t+560)*Dt^4+27*t^2*(54*t^9
            ....: -555*t^8+2678*t^7-7656*t^6+13370*t^5-17723*t^4+13070*t^3
            ....: -6254*t^2+4740*t-644)*Dt^3-3*t*(324*t^10-3915*t^9+20871*t^8
            ....: -67614*t^7+130952*t^6-190111*t^5+180307*t^4-71632*t^3
            ....: +73414*t^2-26368*t-868)*Dt^2+(243*t^11-3645*t^10+21276*t^9
            ....: -77346*t^8+163611*t^7-249067*t^6+297146*t^5-83366*t^4
            ....: +109352*t^3-97772*t^2-4648*t+896)*Dt+162*t^10-1107*t^9
            ....: +5292*t^8-12486*t^7+17908*t^6-37889*t^5-6034*t^4-1970*t^3
            ....: +36056*t^2+2044*t-896)

        We check that the residuals corresponding to various truncated
        solutions (both without and with logs, with lefmost=1/3 and leftmost=0)
        are correctly computed::

            sage: n = 20
            sage: zero = t.parent().zero()

            sage: maj = DiffOpBound(dop, leftmost=0)
            sage: trunc = [t._exp_series(n), zero, zero]
            sage: maj._check_normalized_residual(n, trunc, 0, QQ)
            0

            sage: maj = DiffOpBound(dop, leftmost=1/3)
            sage: trunc = [(1-t).inverse_series_trunc(n), zero, zero]
            sage: maj._check_normalized_residual(n, trunc, 1/3, QQ)
            0
            sage: trunc = [(1-t).inverse_series_trunc(n), zero, 2*t._exp_series(n)]
            sage: maj._check_normalized_residual(n, trunc, 1/3, QQ)
            0
        """
        deg = self.dop.degree()
        logs = max(len(logpol) for logpol in last) if last else 1
        if bwrec_nplus is None:
            bwrec = self.bwrec()
            # Suboptimal: For a given j, we are only going to need the
            # b[i](λ+n+i+ε) for < s - i.
            bwrec_nplus = [bwrec.eval_series(Ring, n+i, logs)
                           for i in xrange(deg)]
        # Check that we have been given/computed enough shifts of the
        # recurrence, and that the orders are consistent. We only have
        # len(bwrec_nplus[0]) - 1 == ordrec >= deg, not ordrec == deg,
        # because bwrec might be of the form ...+(..)*S^(-s)+0*S^(-s-1)+...
        assert (bwrec_nplus == [] and deg == 0
                or len(bwrec_nplus) >= len(bwrec_nplus[0]) - 1 >= deg)

        # res(z) = z^(λ + n)·sum[k,d]( res[k][d]·z^d·log^k(z)/k!)
        #   f(z) = z^(λ + n)·sum[k,d](nres[k][d]·z^d·log^k(z)/k!)
        res = [[None]*deg for _ in xrange(logs)]
        nres = [[None]*deg for _ in xrange(logs)]
        # Since our indicial polynomial is monic,
        # b₀(n) = bwrec_nplus[0][0][0] = lc(dop)(0)·ind(n) = cst·ind(n)
        cst = self.dop.leading_coefficient()[0]
        # For each d, compute the coefficients of z^(λ+n+d)·log(z)^k/k! in the
        # normalized residual. This is done by solving a triangular system with
        # (cst ×) the coefficients of the residual corresponding to the same d
        # on the rhs. The coefficients of the residual are computed on the fly.
        for d in range(deg):
            for k in reversed(range(logs)):
                # Coefficient of z^(λ+n+d)·log(z)^k/k! in dop(ỹ)
                res[k][d] = sum(
                        Ring(bwrec_nplus[d][d+i+1][j])*Ring(last[i][k+j])
                        for i in range(deg - d)
                        for j in range(logs - k))
                # Deduce the corresponding coefficient of nres
                # XXX For simplicity, we limit ourselves to the “generic” case
                # where none of the n+d is a root of the indicial polynomial.
                lc = bwrec_nplus[d][0][0]
                assert not (lc.parent() is IC and lc.contains_zero())
                inv = ~lc
                cor = sum(bwrec_nplus[d][0][u]*nres[k+u][d]
                          for u in range(1, logs-k))
                nres[k][d] = inv*(cst*res[k][d] - cor)
        Poly = self.__CPoly if Ring is IC else self.Poly.change_ring(Ring)
        return [Poly(coeff) for coeff in nres]

    def _check_normalized_residual(self, n, trunc, expo, Ring):
        r"""
        Test the output of normalized_residual().

        This is done by comparing

            monic(dop(z=0,θ))(f(z))      and       dop(ỹ(z)),

        where f(z) is the output of normalized_residual() and ỹ(z) is a
        solution of dop truncated at order O(z^n).

        The parameter trunc must be a list of polynomials such that

            ỹ(z) = z^expo·sum[k](trunc[k](z)·log(z)^k/k!).

        Ideally, Ring should be IC (the default value for the corresponding
        paramter of normalized_residual()) in most cases; unfortunately, this
        often doesn't work due to various weaknesses of Sage.
        """
        ordrec = self.dop.degree()
        last = list(reversed(zip(*(pol.padded_list(n)[n-ordrec:n]
                                   for pol in trunc))))
        coeff = self.normalized_residual(n, last, Ring=Ring)
        from sage.all import log, SR
        z = SR(self.Poly.gen())
        nres = z**(self.leftmost + n)*sum(pol*log(z)**k/ZZ(k).factorial()
                                          for k, pol in enumerate(coeff))
        trunc_full = z**expo*sum(pol*log(z)**k/ZZ(k).factorial()
                                 for k, pol in enumerate(trunc))
        lc = self.dop.leading_coefficient()
        dop0 = self.dop.map_coefficients(lambda pol: pol[0]/lc[0])
        Poly = self.Poly.change_ring(Ring)
        out = (dop0(nres)/z**self.leftmost).expand()
        ref = (self.dop(trunc_full)/z**self.leftmost).expand()
        return (out-ref).expand()

    def rhs(self, n1, normalized_residuals, maj=None):
        r"""
        Compute the right-hand side of a majorant equation valid for each of
        the given normalized residuals.

        INPUT:

        A list of normalized residuals q (as computed by normalized_residual()
        i.e., in particular, with an implicit z^n factor) corresponding to
        solutions y of self.dop truncated to a same order n1. Optionally, a
        HyperexpMajorant maj = self(n0) for some n0 ≤ n1.

        OUTPUT:

        A polynomial (q#)(z) such that, with (q^)(z) = z^n1·(q#)(z),

            z·ŷ'(z) - ŷ(z) = (q^)(z)·v[n0](z)·den(z)                     (*)

        is a majorant equation of self.dop(ỹ) = Q₀(θ)·q(z) (where Q₀ = monic
        indicial polynomial) for all q ∈ normalized_residuals. More precisely,
        if y(z) is a solution of dop(y) = 0 associated to one of the q's, if
        ŷ(z) is a solution of (*), and if

            |y[λ+n,k]| ≤ ŷ[n]   for   n ≥ n1,   0 ≤ k < mult(n, Q₀),     (**)

        then |y[λ+n,k]| ≤ ŷ[n] for *all* n ≥ n1, k ≥ 0. If maj is omitted, the
        bound will hold for any choice of n0 ≤ n1 in (*), but may be coarser
        than that corresponding to a particular n0.

        The typical application is with n0 = n1 larger than the n's
        corresponding to roots λ+n of Q₀ where the y have nonzero initial
        values. In this case, one can take

            ŷ(z) = v[n0](z)·∫(w⁻¹·(q^)(w)·dw, w=0..z)

        and the conditions (**) trivially hold true. (In general, one would
        need to adjust the integration constant so that they do.)

        Note: Some of the above actually makes sense for n1 < n0 as well,
        provided that (**) also hold for n1 ≤ n < n0 and k ≥ 0 and that q^ be
        suitably modified.
        """
        # Let res(z) denote a normalized residual. In general, for any
        # polynomial (res^)(z) s.t. (res^)[n] ≥ |λ+n|*|res[n,k]| for all n, k,
        # the series v[n0](z)*∫(w⁻¹*(res^)(w)/h[n0](w)) where
        # h[n0](z) = v[n0](z)*den(z) is a majorant for the tail of the
        # solution. To make the integral easy to compute, we choose
        # (res^) = (q^)(z)*h[n0](z), i.e., as a polynomial multiple of h.
        nres_bound = bound_polynomials([pol for nres in normalized_residuals
                                            for pol in nres])
        Pols = nres_bound.parent()
        lbda = IC(self.leftmost)
        aux = Pols([(n1 + j)*c for j, c in enumerate(nres_bound)])
        if maj is None:
            # As h[n0](z) has nonnegative coefficients and h[n0](0) = 1, it is
            # always enough to take (q^)[n] ≥ |λ+n|*max[k](|res[n,k]|), that
            # is, (q#)(z) = aux(z).
            return aux
        else:
            # Tighter choice: compute a truncated series expansion f(z) of
            # aux(z)/h(z) s.t. aux(z) = f(z)*h(z) + O(z^(1+deg(aux))). Then,
            # any majorant of f is a valid q^.
            ord = aux.degree() + 1
            inv = maj.exp_part_series0(ord).inverse_series_trunc(ord)
            f = aux._mul_trunc_(inv, ord)
            return Pols([abs(c) for c in f])

    def tail_majorant(self, n, normalized_residuals):
        r"""
        Bound the tails of order ``n`` of solutions of ``self.dop(y) == 0``.

        INPUT:

        A list of normalized residuals q (as computed by normalized_residual(),
        i.e., in particular, with an implicit z^n factor) corresponding to
        solutions y of self.dop truncated to a same order n.

        The truncation order n is required to be larger than all n' such that
        self.leftmost + n' is a root of the indicial polynomial of self.dop,
        and the solution of interest has nonzero initial values there.

        OUTPUT:

        A HyperexpMajorant representing a common majorant series for the
        tails y[n:](z) of the corresponding solutions.
        """
        # XXX Perhaps add a way to pass an existing maj (= self(n0), n0 <= n)
        # or an n0 as parameter.
        maj = self(n)
        # XXX Better without maj? (speed/tightness trade-off)
        rhs = self.rhs(n, normalized_residuals, maj)
        logger.debug("n=%s, maj(n)=%s, rhs=%s", n, maj, rhs)
        # Shift by n to account for the implicit z^n, then by -1 because of the
        # formula ∫(w⁻¹·(q^)(w)·dw.
        pol = (rhs << (n - 1)).integral() # XXX potential perf issue with <<
        maj *= pol
        return maj

    def matrix_sol_tail_bound(self, n, rad, normalized_residuals, rows=None):
        r"""
        Bound the Frobenius norm of the tail starting of order ``n`` of the
        series expansion of the matrix ``(y_j^(i)(z)/i!)_{i,j}`` where the
        ``y_j`` are the solutions associated to the elements of
        ``normalized_residuals``, and ``0 ≤ j < rows``. The bound is valid for
        ``|z| < rad``.
        """
        if rows is None:
            rows=self.dop.order()
        maj = self.tail_majorant(n, normalized_residuals)
        # Since (y[n:])' << maj => (y')[n:] << maj, this bound is valid for the
        # tails of a column of the form [y, y', y''/2, y'''/6, ...] or
        # [y, θy, θ²y/2, θ³y/6, ...].
        col_bound = maj.bound(rad, derivatives=rows)
        return (IR(rows).sqrt()*col_bound).above_abs()

    def _test(self, ini=None, prec=100):
        r"""
        Check that the majorants produced by this DiffOpBound bound the tails
        of the solutions of the associated operator.

        This is a heuristic check for testing purposes, nothing rigorous!

        This method currently does not support regular singular points.

        EXAMPLES::

            sage: from ore_algebra import *
            sage: from ore_algebra.analytic.bounds import *
            sage: Dops, x, Dx = DifferentialOperators()
            sage: maj = DiffOpBound(Dx - 1)
            sage: maj._test()
            sage: maj._test([3], 200)
        """
        if (self._dop_D.leading_coefficient()[0].is_zero()
                or not self.leftmost.is_zero()):
            raise NotImplementedError
        ord = self.dop.order()
        if ini is None:
            from sage.rings.number_field.number_field import QuadraticField
            QQi = QuadraticField(-1)
            ini = [QQi.random_element() for _ in xrange(ord)]
        sol = self.dop.power_series_solutions(prec)
        Series = PowerSeriesRing(CBF, self.dop.base_ring().variable_name())
        ref = sum((ini[k]*sol[k] for k in xrange(ord)), Series(0)).polynomial()
        # XXX This won't work at regular singular points (even for power series
        # solutions), because tail_majorant(), by basing on rhs(), assumes that
        # we are past all nonzero initial conditions.
        for n in [ord, ord + 1, ord + 2, ord + 50]:
            logger.info("truncation order = %d", n)
            if n + 30 >= prec:
                warnings.warn("insufficient precision")
            last = [[ref[n-i]] for i in range(1, self.dop.degree() + 1)]
            resid = self.normalized_residual(n, last)
            maj = self.tail_majorant(n, [resid])
            tail = (ref >> n) << n
            maj_ser = maj.bound_series(0, n + 30)
            logger.info(["|{}| <= {}".format(tail[i], maj_ser[i])
                         for i in range(n + 30)])
            maj._test(tail)

# Perhaps better: work with a "true" Ore algebra K[θ][z]. Use Euclidean
# division to compute the truncation in DiffOpBound._update_num_bound.
# Extracting the Qj(θ) would then be easy, and I may no longer need the
# coefficients of θ "on the right".
def _dop_rcoeffs_of_T(dop, base_ring):
    r"""
    Compute the coefficients of dop as an operator in θ but with θ on the left.

    EXAMPLES::

        sage: from ore_algebra import OreAlgebra
        sage: from ore_algebra.analytic.bounds import _dop_rcoeffs_of_T
        sage: Pols.<x> = QQ[]; Dops.<Tx> = OreAlgebra(Pols)
        sage: dop = (1/250*x^4 + 21/50*x^3)*Tx - 6/125*x^4 + 6/25*x^3
        sage: coeff = _dop_rcoeffs_of_T(dop, QQ); coeff
        [-8/125*x^4 - 51/50*x^3, 1/250*x^4 + 21/50*x^3]
        sage: sum(Tx^i*c for i, c in enumerate(coeff)) == dop
        True

    TESTS::

        sage: _dop_rcoeffs_of_T(Dops.zero(), QQ)
        []
        sage: _dop_rcoeffs_of_T(Dops.one(), QQ)
        [1]
        sage: _dop_rcoeffs_of_T(Dops.gen(), QQ)
        [0, 1]
    """
    assert dop.parent().is_T()
    Pols = dop.base_ring().change_ring(base_ring)
    ordlen, deglen = dop.order() + 1, dop.degree() + 1
    binomial = [[0]*(ordlen) for _ in range(ordlen)]
    for n in range(ordlen):
        binomial[n][0] = 1
        for k in range(1, n + 1):
            binomial[n][k] = binomial[n-1][k-1] + binomial[n-1][k]
    res = [None]*(ordlen)
    for k in range(ordlen):
        pol = [0]*(deglen)
        for j in range(deglen):
            pow = 1
            for i in range(ordlen - k):
                pol[j] += pow*binomial[k+i][i]*dop[k+i][j]
                pow *= (-j)
        res[k] = Pols(pol)
    return res

@random_testing
def _test_diffop_bound(
        ords=xrange(1, 5),
        degs=xrange(5),
        pplens=[1, 2, 5],
        prec=100,
        verbose=False
    ):
    r"""
    Randomized testing of :func:`DiffOpBound`.

    EXAMPLES::

    Just an example of how to use this function; the real tests are run from
    the docstring of DiffOpBound. ::

        sage: from ore_algebra.analytic.bounds import _test_diffop_bound
        sage: _test_diffop_bound(ords=[2], degs=[2], pplens=[1], prec=100,
        ....:         seed=0, verbose=True)
        testing operator: ((1/457*i - 3/457)*x^2 + (-1/457*i + 1/457)*x
        + 1/457*i - 6/457)*Dx^2 + ((-2/53*i + 2/53)*x - 1/106*i + 1/106)*Dx
        + (-6/107*i - 1/107)*x^2 + (1/214*i + 1/107)*x
    """
    from sage.rings.number_field.number_field import QuadraticField

    QQi = QuadraticField(-1, 'i')
    Pols, x = PolynomialRing(QQi, 'x').objgen()
    Dops, Dx = ore_algebra.OreAlgebra(Pols, 'Dx').objgen()

    for ord in ords:
        for deg in degs:
            dop = Dops(0)
            while dop.leading_coefficient()(0).is_zero():
                dop = Dops([Pols.random_element(degree=(0, deg))
                                /ZZ.random_element(1,1000)
                            for _ in xrange(ord + 1)])
            if verbose:
                print("testing operator:", dop)
            for pplen in pplens:
                maj = DiffOpBound(dop, pol_part_len=pplen)
                maj._test(prec=prec)

def _switch_vars(pol):
    Ax = pol.base_ring()
    x = Ax.variable_name()
    y = pol.variable_name()
    Ay = PolynomialRing(Ax.base_ring(), y)
    Ayx = PolynomialRing(Ay, x)
    if pol.is_zero():
        return Ayx.zero()
    dy = pol.degree()
    dx = max(c.degree() for c in pol)
    return Ayx([Ay([pol[j][i] for j in range(dy+1)]) for i in range(dx+1)])
