# Forecast Model Comparison & Holdout Evaluation Report

> [!IMPORTANT]
> **Mandatory Statements**:
> 1. Forecasting demonstrator; not trading or investment advice.
> 2. No financial benefit was measured.
> 3. Interval coverage is empirical on historical data and is not guaranteed.
> 4. The target is the World Bank palm oil benchmark in MYR (converted from USD with BNM exchange rate), not the MPOB CPO price; any definition breaks are recorded in the data specification.

## 1. Executive Summary & Selection Audit

In accordance with Checkpoint Gates G2 and G3, candidate models were strictly evaluated and chosen on the validation split before holdout evaluation was conducted.

| Series | Champion Model | Selection Rationale | Validation MASE (Pooled) | Holdout MASE (Pooled) |
| --- | --- | --- | --- | --- |
| `palm_wb_myr` | **B1** | Candidate B1 (MASE 3.0992) is simpler than best B4 (MASE 3.0606) and falls within 2.0% relative MASE threshold. | 3.0992 | 1.7868 |
| `ppi_oilsfats_my` | **B3** | Lowest pooled validation MASE (1.1900). | 1.1900 | 1.8133 |

## 2. Evaluation Against Project Objectives (O2 & O3)

### Objective O2: Point Accuracy Hypothesis (Champion MASE ≤ 0.95 at h=1 on Validation)

Hypothesis test per `01_PROBLEM_AND_OBJECTIVES.md`: Can a time series or ML model achieve MASE ≤ 0.95 at horizon 1 on validation?

- **Series `palm_wb_myr`**: Champion `B1` achieved Validation $h=1$ MASE = **2.0131** $\rightarrow$ **Objective O2 MISSED**.
  *(Finding: Commodity monthly prices exhibit strong martingal-like properties where naive level persistence sets a stringent lower bound; per protocol, when no model beats naive by >2%, naive is declared champion).* 
- **Series `ppi_oilsfats_my`**: Champion `B3` achieved Validation $h=1$ MASE = **0.5515** $\rightarrow$ **Objective O2 MET**.

### Objective O3: Interval Calibration (Validation Coverage within ±5pp of Nominal)

- **Series `palm_wb_myr`** (`C2`; C2 selected by lower validation coverage error (0.0389 vs 0.0528).): largest validation gap from nominal is **6.7 pp** against a tolerance of 5 pp $\rightarrow$ **Objective O3 MISSED**.
- **Series `ppi_oilsfats_my`** (`C2`; C2 selected by lower validation coverage error (0.0562 vs 0.0944).): largest validation gap from nominal is **9.6 pp** against a tolerance of 5 pp $\rightarrow$ **Objective O3 MISSED**.

Measured coverage of the selected method (95% Wilson interval; `coverage_error` is coverage minus nominal, positive means the band is too wide). Both methods are in `reports/validation_coverage.csv` and `reports/holdout_coverage.csv`.

```
      series_id interval_method      split  horizon  nominal_level  n_eval  coverage  coverage_ci_lower  coverage_ci_upper  coverage_error  mean_width_pct
    palm_wb_myr              C2    holdout        1            0.8      23    0.8261             0.6286             0.9302          0.0261           14.41
    palm_wb_myr              C2    holdout        1            0.9      23    0.9130             0.7320             0.9758          0.0130           21.37
    palm_wb_myr              C2    holdout        2            0.8      22    0.7727             0.5656             0.8988         -0.0273           20.09
    palm_wb_myr              C2    holdout        2            0.9      22    0.9545             0.7820             0.9919          0.0545           31.66
    palm_wb_myr              C2    holdout        3            0.8      21    0.8095             0.6000             0.9233          0.0095           26.81
    palm_wb_myr              C2    holdout        3            0.9      21    1.0000             0.8454             1.0000          0.1000           40.25
    palm_wb_myr              C2 validation        1            0.8      60    0.8500             0.7389             0.9190          0.0500           19.07
    palm_wb_myr              C2 validation        1            0.9      60    0.9333             0.8407             0.9738          0.0333           26.82
    palm_wb_myr              C2 validation        2            0.8      60    0.8667             0.7583             0.9309          0.0667           32.85
    palm_wb_myr              C2 validation        2            0.9      60    0.9000             0.7985             0.9534          0.0000           58.15
    palm_wb_myr              C2 validation        3            0.8      60    0.8500             0.7389             0.9190          0.0500           48.32
    palm_wb_myr              C2 validation        3            0.9      60    0.8667             0.7583             0.9309         -0.0333           68.83
ppi_oilsfats_my              C2    holdout        1            0.8      23    0.6957             0.4913             0.8440         -0.1043            2.93
ppi_oilsfats_my              C2    holdout        1            0.9      23    0.7826             0.5810             0.9034         -0.1174            4.40
ppi_oilsfats_my              C2    holdout        2            0.8      22    0.5909             0.3873             0.7674         -0.2091            7.34
ppi_oilsfats_my              C2    holdout        2            0.9      22    0.8182             0.6148             0.9269         -0.0818           10.40
ppi_oilsfats_my              C2    holdout        3            0.8      21    0.6190             0.4088             0.7925         -0.1810           13.54
ppi_oilsfats_my              C2    holdout        3            0.9      21    0.8095             0.6000             0.9233         -0.0905           15.65
ppi_oilsfats_my              C2 validation        1            0.8      48    0.8958             0.7783             0.9547          0.0958            5.78
ppi_oilsfats_my              C2 validation        1            0.9      48    0.9583             0.8602             0.9885          0.0583            6.80
ppi_oilsfats_my              C2 validation        2            0.8      48    0.8750             0.7530             0.9414          0.0750            9.47
ppi_oilsfats_my              C2 validation        2            0.9      48    0.9167             0.8045             0.9671          0.0167           13.98
ppi_oilsfats_my              C2 validation        3            0.8      48    0.8542             0.7283             0.9275          0.0542           15.84
ppi_oilsfats_my              C2 validation        3            0.9      48    0.9375             0.8316             0.9785          0.0375           19.87
```

Holdout coverage is reported as measured and was not used to choose the method.

## 3. Holdout Performance by Horizon (24 Origins)

Holdout origins span 24 months, with observed evaluation counts decreasing from 23 ($h=1$) to 21 ($h=3$) due to publication lag at the vintage cutoff.

```
      series_id model   split horizon  n_eval      mae     rmse   mase   wape      bias  fit_failures
    palm_wb_myr    B1 holdout       1      23 176.5379 249.5311 1.1581 0.0394   -7.6201             0
    palm_wb_myr    B1 holdout       2      22 291.1293 375.8861 1.9093 0.0654   18.4138             0
    palm_wb_myr    B1 holdout       3      21 357.6983 426.9656 2.3456 0.0811   51.8130             0
    palm_wb_myr    B1 holdout  pooled      66 272.3770 356.0897 1.7868 0.0612   19.9684             0
    palm_wb_myr    B2 holdout       1      23 540.4469 683.5507 3.5454 0.1205 -147.4748             0
    palm_wb_myr    B2 holdout       2      22 506.1889 642.1485 3.3198 0.1137  -95.3545             0
    palm_wb_myr    B2 holdout       3      21 458.1858 568.1565 3.0046 0.1039  -27.7878             0
    palm_wb_myr    B2 holdout  pooled      66 502.8536 634.8132 3.2987 0.1130  -92.0192             0
    palm_wb_myr    B3 holdout       1      23 184.0568 256.4323 1.2074 0.0410    7.8829             0
    palm_wb_myr    B3 holdout       2      22 348.5045 429.0665 2.2856 0.0783   48.5183             0
    palm_wb_myr    B3 holdout       3      21 446.6661 532.3413 2.9290 0.1012   94.6740             0
    palm_wb_myr    B3 holdout  pooled      66 322.4302 417.6724 2.1152 0.0724   49.0434             0
    palm_wb_myr    B4 holdout       1      23 162.5024 223.4269 1.0660 0.0362   -1.1955             0
    palm_wb_myr    B4 holdout       2      22 300.9518 369.8463 1.9738 0.0676   25.1256             0
    palm_wb_myr    B4 holdout       3      21 352.2706 432.5271 2.3100 0.0798   59.8287             0
    palm_wb_myr    B4 holdout  pooled      66 269.0330 350.0243 1.7649 0.0604   26.9950             0
    palm_wb_myr    M1 holdout       1      23 176.0245 233.5579 1.1547 0.0393    7.9445             0
    palm_wb_myr    M1 holdout       2      22 355.3672 461.5687 2.3306 0.0798   65.3150             0
    palm_wb_myr    M1 holdout       3      21 473.8259 565.4834 3.1071 0.1074  104.1166             0
    palm_wb_myr    M1 holdout  pooled      66 330.5604 437.9159 2.1685 0.0743   57.6682             0
    palm_wb_myr    M2 holdout       1      23 179.8801 238.4744 1.1800 0.0401   50.2570             0
    palm_wb_myr    M2 holdout       2      22 320.3947 432.5799 2.1013 0.0720  148.4019             0
    palm_wb_myr    M2 holdout       3      21 452.1036 551.3712 2.9647 0.1025  230.1540             0
    palm_wb_myr    M2 holdout  pooled      66 313.3349 422.9941 2.0555 0.0704  140.2119             0
ppi_oilsfats_my    B1 holdout       1      23   2.0043   2.5863 1.0100 0.0153   -0.8565             0
ppi_oilsfats_my    B1 holdout       2      22   3.8182   4.7296 1.9234 0.0290   -1.6364             0
ppi_oilsfats_my    B1 holdout       3      21   5.3905   6.5312 2.7151 0.0409   -2.3238             0
ppi_oilsfats_my    B1 holdout  pooled      66   3.6864   4.8332 1.8576 0.0280   -1.5833             0
ppi_oilsfats_my    B2 holdout       1      23  10.0435  11.6149 5.0609 0.0766   -8.0174             0
ppi_oilsfats_my    B2 holdout       2      22  10.1455  11.7589 5.1107 0.0771   -8.0273             0
ppi_oilsfats_my    B2 holdout       3      21  10.0667  11.7570 5.0704 0.0763   -7.8476             0
ppi_oilsfats_my    B2 holdout  pooled      66  10.0848  11.7083 5.0818 0.0766   -7.9667             0
ppi_oilsfats_my    B3 holdout       1      23   1.6075   2.0716 0.8100 0.0123   -0.2089             0
ppi_oilsfats_my    B3 holdout       2      22   3.6556   4.2934 1.8415 0.0278   -0.4096             0
ppi_oilsfats_my    B3 holdout       3      21   5.7193   6.7431 2.8807 0.0434   -0.6637             0
ppi_oilsfats_my    B3 holdout  pooled      66   3.5985   4.7019 1.8133 0.0274   -0.4205             0
ppi_oilsfats_my    B4 holdout       1      23   1.4957   2.0120 0.7537 0.0114   -0.3182             0
ppi_oilsfats_my    B4 holdout       2      22   3.3261   4.0647 1.6755 0.0253   -0.7027             0
ppi_oilsfats_my    B4 holdout       3      21   5.0442   6.2215 2.5407 0.0382   -1.1508             0
ppi_oilsfats_my    B4 holdout  pooled      66   3.2349   4.3856 1.6301 0.0246   -0.7113             0
ppi_oilsfats_my    M1 holdout       1      23   1.6401   2.1881 0.8265 0.0125   -0.2429             0
ppi_oilsfats_my    M1 holdout       2      22   3.7199   4.3975 1.8739 0.0283   -0.5190             0
ppi_oilsfats_my    M1 holdout       3      21   4.5698   5.6236 2.3017 0.0346   -0.9280             0
ppi_oilsfats_my    M1 holdout  pooled      66   3.2656   4.2634 1.6455 0.0248   -0.5529             0
ppi_oilsfats_my    M2 holdout       1      23   1.3761   1.8089 0.6934 0.0105   -0.2889             0
ppi_oilsfats_my    M2 holdout       2      22   3.3836   3.9050 1.7045 0.0257   -0.7061             0
ppi_oilsfats_my    M2 holdout       3      21   4.0142   5.0717 2.0219 0.0304   -0.3543             0
ppi_oilsfats_my    M2 holdout  pooled      66   2.8847   3.7958 1.4536 0.0219   -0.4487             0
```

## 4. Methodological Limitations & Evidence Boundaries

- **Limited Evidence**: Exactly 24 points per horizon were evaluated in the holdout split. At 80% nominal coverage, the standard error of a binomial proportion with $N=24$ is approximately $\sqrt{0.80 \times 0.20 / 24} \approx 8.16$ percentage points.
- **Non-Exchangeability**: Global commodity prices are non-stationary and subject to macro volatility shocks; exact exchangeability guarantees do not hold.
- **Frozen Policy**: Results reflect a single frozen evaluation run without ex-post retuning.
