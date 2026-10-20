"""Build IDW WiFi RSSI map; evaluate on held-out locations (not random samples)."""
import argparse
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt


def idw(train_xy, train_rssi, query_xy, power=2, eps=1e-9):
    dist = np.linalg.norm(query_xy[:, None, :] - train_xy[None, :, :], axis=2)
    close = dist < 1e-8
    weights = 1.0 / np.maximum(dist, eps) ** power
    estimates = (weights @ train_rssi) / weights.sum(axis=1)
    if close.any():
        for i in np.where(close.any(axis=1))[0]:
            estimates[i] = np.mean(train_rssi[close[i]])
    return estimates


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--input', default='measurements.csv')
    p.add_argument('--width', type=float, default=10)
    p.add_argument('--height', type=float, default=10)
    p.add_argument('--power', type=float, default=2)
    p.add_argument('--output', default='wifi_heatmap.png')
    args = p.parse_args()
    df = pd.read_csv(args.input)
    if df.empty:
        raise SystemExit('No measurements.')
    if df.bssid.nunique() != 1:
        raise SystemExit('Multiple BSSIDs found: filter data to one router BSSID before mapping.')
    grouped = df.groupby(['point_id', 'x_m', 'y_m', 'split'], as_index=False).agg(
        rssi_dbm=('rssi_dbm', 'median'), count=('rssi_dbm', 'size'))
    train = grouped[grouped.split == 'train']
    test = grouped[grouped.split == 'test']
    if len(train) < 4:
        raise SystemExit('Collect at least 4 distinct training locations.')
    if train[['x_m', 'y_m']].drop_duplicates().shape[0] < 4:
        raise SystemExit('Need 4 distinct coordinate pairs.')
    xy = train[['x_m', 'y_m']].to_numpy(float)
    z = train.rssi_dbm.to_numpy(float)
    gx, gy = np.meshgrid(np.linspace(0, args.width, 160), np.linspace(0, args.height, 160))
    zz = idw(xy, z, np.column_stack([gx.ravel(), gy.ravel()]), args.power).reshape(gx.shape)
    fig, ax = plt.subplots(figsize=(8, 6))
    im = ax.imshow(zz, origin='lower', extent=[0, args.width, 0, args.height],
                   aspect='equal', cmap='turbo', vmin=-95, vmax=-30)
    ax.scatter(train.x_m, train.y_m, c='white', edgecolor='black', s=35, label='Training points')
    if len(test):
        q = test[['x_m', 'y_m']].to_numpy(float)
        pred = idw(xy, z, q, args.power)
        err = pred - test.rssi_dbm.to_numpy(float)
        rmse = float(np.sqrt(np.mean(err**2)))
        mae = float(np.mean(np.abs(err)))
        print(f'Held-out test locations: {len(test)}; MAE={mae:.2f} dB; RMSE={rmse:.2f} dB')
        out = test.copy()
        out['predicted_dbm'] = pred
        out['error_db'] = err
        out.to_csv('validation_results.csv', index=False)
        ax.scatter(test.x_m, test.y_m, marker='x', c='black', s=60, label='Held-out test')
    else:
        print('No held-out test locations; map only, accuracy not assessed.')
    ax.set(xlabel='x (m)', ylabel='y (m)', title='WiFi RSSI spatial map (IDW interpolation)')
    ax.legend(loc='upper right')
    fig.colorbar(im, ax=ax, label='Estimated RSSI (dBm)')
    fig.tight_layout()
    fig.savefig(args.output, dpi=180)
    print(f'Saved {args.output}')


if __name__ == '__main__':
    main()
