% Stack
%secs = secs(sec_nums);
%secs = {secA, secB};
alignment = 'z';

last_cell = sum(~cellfun('isempty',secs));
% Output folder
folder_name = sprintf('%s_Secs%d-%d_%s', secs{1}.wafer, secs{1}.num, secs{last_cell}.num, alignment);
render_path = create_folder(fullfile(renderpath, folder_name));

% Clear any loaded images to save memory
%secs = cellfun(@imclear_sec, secs, 'UniformOutput', false);

total_time = tic;
%% Find stack spatial reference
tile_Rs = cell(length(secs), 1);
for s = 1:length(secs)
    % For convenience
    sec = secs{s};
    tforms = sec.alignments.(alignment).tforms;
    
    % Get initial spatial references before alignment
    initial_Rs = cellfun(@imref2d, sec.tile_sizes, 'UniformOutput', false);
    
    % Estimate spatial references after alignment
    tile_Rs{s} = cellfun(@tform_spatial_ref, initial_Rs', tforms, 'UniformOutput', false);
end

% Merge all tile references to find stack reference
stack_R = merge_spatial_refs(vertcat(tile_Rs{:}));

fprintf('Calculated and merged output spatial references. [%.2fs]\n', toc(total_time))

%% Render each section
for s = 1:length(secs)
    render_time = tic;
    % Convenience
    sec = secs{s};
    tforms = sec.alignments.(alignment).tforms;
    sec_tile_Rs = tile_Rs{s};

    % Transform tiles
    sec_num = sec.num;
    wafer_path = waferpath;
    tiles = cell(sec.num_tiles, 1);
    parfor t = 1:sec.num_tiles
        % Transform tile
        tiles{t} = imwarp(imload_tile(sec_num, t, 1.0, wafer_path), tforms{t}, 'OutputView', sec_tile_Rs{t});
    end

    % Blend tiles into section
    section = zeros(stack_R.ImageSize, 'uint8');
    for t = 1:sec.num_tiles
        % Find tile subscripts within section image
        [I, J] = stack_R.worldToSubscript(sec_tile_Rs{t}.XWorldLimits, sec_tile_Rs{t}.YWorldLimits);

        % Blend into section
        section(I(1):I(2)-1, J(1):J(2)-1) = max(section(I(1):I(2)-1, J(1):J(2)-1), tiles{t});
        tiles{t} = [];
    end

    % Write to disk without overwriting existing
    sec_filename = [sec.name '-' alignment '.tif'];
    imwrite(section, get_new_path(fullfile(render_path, sec_filename)));
    
    fprintf('Rendered section %d (%d/%d). [%.2fs]\n', sec.num, s, length(secs), toc(render_time))
    clear section tiles sec
end
fprintf('<strong>Done rendering %d sections. [%.2fs]</strong>\n', length(secs), toc(total_time));