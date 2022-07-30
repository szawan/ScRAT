import os
import torch
import numpy as np
import copy
from torch.utils.data import Dataset
import pdb
from tqdm import tqdm


class MyDataset(Dataset):
    def __init__(self, x_train, x_valid, x_test, y_train, y_valid, y_test, id_train, id_test, fold='train'):
        fold = fold.lower()

        self.train = False
        self.test = False
        self.val = False

        if fold == "train":
            self.train = True
        elif fold == "test":
            self.test = True
        elif fold == "val":
            self.val = True
        else:
            raise RuntimeError("Not train-val-test")

        self.x_train = x_train
        self.x_valid = x_valid
        self.x_test = x_test
        self.y_train = y_train
        self.y_valid = y_valid
        self.y_test = y_test
        self.id_train = id_train
        self.id_test = id_test

    def __len__(self):
        if self.train:
            return len(self.x_train)
        elif self.test:
            return len(self.x_test)
        elif self.val:
            return len(self.x_valid)

    def __getitem__(self, index):
        if self.train:
            x, y, cell_id = torch.from_numpy(np.array(self.x_train[index])), \
                            torch.from_numpy(self.y_train[index]).float(), self.id_train[index]
        elif self.test:
            x, y, cell_id = torch.from_numpy(np.array(self.x_test[index])), \
                            torch.from_numpy(self.y_test[index]).float(), self.id_test[index]
        elif self.val:
            x, y, cell_id = torch.from_numpy(np.array(self.x_valid[index])), \
                            torch.from_numpy(self.y_valid[index]).float(), []

        return x, y, cell_id

    def collate(self, batches):
        xs = torch.stack([batch[0] for batch in batches if len(batch) > 0])
        mask = torch.stack([batch[0] == -1 for batch in batches if len(batch) > 0])
        ys = torch.stack([batch[1] for batch in batches if len(batch) > 0])
        ids = [batch[2] for batch in batches if len(batch) > 0]
        return xs, torch.FloatTensor(ys), ids, mask


def add_noise(cells):
    mean = 0
    var = 1e-5
    sigma = var ** 0.5
    gauss = np.random.normal(mean, sigma, cells.shape)
    noisy = cells + gauss
    return noisy


def mixup(x, x_p, alpha=1.0, size=1, lam=None):
    batch_size = min(x.shape[0], x_p.shape[0])
    if lam == None:
        lam = np.random.beta(alpha, alpha)
        if size > 1:
            lam = np.random.beta(alpha, alpha, size=size).reshape([-1, 1])
    # x = np.random.permutation(x)
    # x_p = np.random.permutation(x_p)
    x_mix = lam * x[:batch_size] + (1 - lam) * x_p[:batch_size]
    return x_mix, lam


def mixups(args, data, p_idx, labels_, cell_type):
    max_num_cells = data.shape[0]
    ###################
    # check the dataset
    for i, pp in enumerate(p_idx):
        if len(set(labels_[pp])) > 1:
            print(i)
    ###################
    for idx, i in enumerate(p_idx):
        max_num_cells += (max(args.min_size - len(i), 0) + 100)
    data_augmented = np.zeros([max_num_cells + (args.min_size + 100) * args.augment_num, data.shape[1]])
    if args.intra_only and args.intra_mixup:
        last = 0
        labels_augmented = []
        cell_type_augmented = []
    else:
        data_augmented[:data.shape[0]] = data
        last = data.shape[0]
        labels_augmented = copy.deepcopy(labels_)
        cell_type_augmented = copy.deepcopy(cell_type)
    # intra-mixup
    if args.intra_mixup:
        print("======= intra patient mixup ... ============")
        if args.intra_only:
            for idx, i in (enumerate(p_idx)):
                diff = 0
                sampled_idx_1 = []
                sampled_idx_2 = []
                temp_set = sorted(set(cell_type[i]))
                for ct in temp_set:
                    i_sub = i[cell_type[i] == ct]
                    diff_sub = len(i_sub)
                    sampled_idx_1 += np.random.choice(i_sub, len(i_sub), replace=False).tolist()
                    sampled_idx_2 += np.random.choice(i_sub, len(i_sub), replace=False).tolist()
                    if args.min_size > len(i):
                        diff_sub_ = max((args.min_size - len(i)) * len(i_sub) // len(i), 1)
                        diff_sub += diff_sub_
                        sampled_idx_1 += np.random.choice(i_sub, diff_sub_).tolist()
                        sampled_idx_2 += np.random.choice(i_sub, diff_sub_).tolist()
                    cell_type_augmented = np.concatenate([cell_type_augmented, [ct] * diff_sub])
                    diff += diff_sub
                if args.mix_type == 1:
                    x_mix, _ = mixup(data[sampled_idx_1], data[sampled_idx_2], alpha=args.alpha,
                                     size=len(sampled_idx_1))
                else:
                    x_mix, _ = mixup(data[sampled_idx_1], data[sampled_idx_2], alpha=args.alpha)
                data_augmented[last:(last + x_mix.shape[0])] = x_mix
                last += x_mix.shape[0]
                labels_augmented = np.concatenate([labels_augmented, [labels_[i[0]]] * diff])
                p_idx[idx] = np.arange(labels_augmented.shape[0] - diff, labels_augmented.shape[0])
        else:
            for idx, i in enumerate(p_idx):
                if len(i) < args.min_size:
                    diff = 0
                    sampled_idx_1 = []
                    sampled_idx_2 = []
                    temp_set = sorted(set(cell_type[i]))
                    for ct in temp_set:
                        i_sub = i[cell_type[i] == ct]
                        diff_sub = max((args.min_size - len(i)) * len(i_sub) // len(i), 1)
                        sampled_idx_1 += np.random.choice(i_sub, diff_sub).tolist()
                        sampled_idx_2 += np.random.choice(i_sub, diff_sub).tolist()
                        cell_type_augmented = np.concatenate([cell_type_augmented, [ct] * diff_sub])
                        diff += diff_sub
                    if args.mix_type == 1:
                        x_mix, _ = mixup(data[sampled_idx_1], data[sampled_idx_2], alpha=args.alpha,
                                         size=len(sampled_idx_1))
                    else:
                        x_mix, _ = mixup(data[sampled_idx_1], data[sampled_idx_2], alpha=args.alpha)
                    data_augmented[last:(last + x_mix.shape[0])] = x_mix
                    last += x_mix.shape[0]
                    labels_augmented = np.concatenate([labels_augmented, [labels_augmented[i[0]]] * diff])
                    p_idx[idx] = np.concatenate(
                        [i, np.arange(labels_augmented.shape[0] - diff, labels_augmented.shape[0])])

    if args.same_pheno != 0:
        p_idx_per_pheno = {}
        for pp in p_idx:
            y = labels_augmented[pp[0]]
            if p_idx_per_pheno.get(y, -2) == -2:
                p_idx_per_pheno[y] = [pp]
            else:
                p_idx_per_pheno[y].append(pp)

    if args.inter_only and (args.augment_num > 0):
        p_idx_augmented = []
    else:
        p_idx_augmented = copy.deepcopy(p_idx)
    # inter-mixup
    if args.augment_num > 0:
        print("======= inter patient mixup ... ============")
        for i in tqdm(range(args.augment_num)):
            lam = np.random.beta(args.alpha, args.alpha)
            if args.same_pheno == 1:
                temp_label = np.random.randint(len(p_idx_per_pheno))
                id_1, id_2 = np.random.randint(len(p_idx_per_pheno[temp_label]), size=2)
                idx_1, idx_2 = p_idx_per_pheno[temp_label][id_1], p_idx_per_pheno[temp_label][id_2]
            elif args.same_pheno == -1:
                i_1, i_2 = np.random.choice(len(p_idx_per_pheno), 2, replace=False)
                id_1 = np.random.randint(len(p_idx_per_pheno[i_1]))
                id_2 = np.random.randint(len(p_idx_per_pheno[i_2]))
                idx_1, idx_2 = p_idx_per_pheno[i_1][id_1], p_idx_per_pheno[i_2][id_2]
            else:
                id_1, id_2 = np.random.randint(len(p_idx), size=2)
                idx_1, idx_2 = p_idx[id_1], p_idx[id_2]
            diff = 0
            set_union = sorted(set(cell_type_augmented[idx_1]).union(set(cell_type_augmented[idx_2])))
            while diff < (args.min_size // 2):
                for ct in set_union:
                    i_sub_1 = idx_1[cell_type_augmented[idx_1] == ct]
                    i_sub_2 = idx_2[cell_type_augmented[idx_2] == ct]
                    diff_sub = max(
                        int(args.min_size * (lam * len(i_sub_1) / len(idx_1) + (1 - lam) * len(i_sub_2) / len(idx_2))),
                        1)
                    diff += diff_sub
                    if len(i_sub_1) == 0:
                        sampled_idx_1 = [-1] * diff_sub
                        sampled_idx_2 = np.random.choice(i_sub_2, diff_sub)
                        x_mix, _ = mixup(data_augmented[sampled_idx_1], data_augmented[sampled_idx_2], alpha=args.alpha,
                                         lam=lam)
                        x_mix = add_noise(x_mix)
                    elif len(i_sub_2) == 0:
                        sampled_idx_1 = np.random.choice(i_sub_1, diff_sub)
                        sampled_idx_2 = [-1] * diff_sub
                        x_mix, _ = mixup(data_augmented[sampled_idx_1], data_augmented[sampled_idx_2], alpha=args.alpha,
                                         lam=lam)
                        x_mix = add_noise(x_mix)
                    else:
                        sampled_idx_1 = np.random.choice(i_sub_1, diff_sub)
                        sampled_idx_2 = np.random.choice(i_sub_2, diff_sub)
                        x_mix, _ = mixup(data_augmented[sampled_idx_1], data_augmented[sampled_idx_2], alpha=args.alpha,
                                         lam=lam)
                    data_augmented[last:(last + x_mix.shape[0])] = x_mix
                    last += x_mix.shape[0]
            labels_augmented = np.concatenate(
                [labels_augmented, [lam * labels_augmented[idx_1[0]] + (1 - lam) * labels_augmented[idx_2[0]]] * diff])
            p_idx_augmented.append(np.arange(labels_augmented.shape[0] - diff, labels_augmented.shape[0]))

    return data_augmented[:last], p_idx_augmented, labels_augmented


def sampling(args, train_p_idx, test_p_idx, labels_, labels_augmented):
    if args.all == 0:
        individual_train = []
        individual_test = []
        for idx in train_p_idx:
            y = labels_augmented[idx[0]]
            temp = []
            if idx.shape[0] < args.train_sample_cells:
                for _ in range(args.train_num_sample):
                    sample = np.zeros(args.train_sample_cells, dtype=int) - 1
                    sample[:idx.shape[0]] = idx
                    temp.append((sample, y))
            else:
                for _ in range(args.train_num_sample):
                    sample = np.random.choice(idx, args.train_sample_cells, replace=False)
                    temp.append((sample, y))
            individual_train.append(temp)
        for idx in test_p_idx:
            y = labels_[idx[0]]
            if idx.shape[0] < args.test_sample_cells:
                sample_cells = idx.shape[0]
            else:
                sample_cells = args.test_sample_cells
            temp = []
            for _ in range(args.test_num_sample):
                sample = np.random.choice(idx, sample_cells, replace=False)
                temp.append((sample, y))
            individual_test.append(temp)
    else:
        individual_train = []
        individual_test = []
        for idx in train_p_idx:
            y = labels_augmented[idx[0]]
            temp = []
            sample = idx
            temp.append((sample, y))
            individual_train.append(temp)
        for idx in test_p_idx:
            y = labels_[idx[0]]
            temp = []
            sample = idx
            temp.append((sample, y))
            individual_test.append(temp)

    return individual_train, individual_test